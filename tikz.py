"tikz, a Python interface to TikZ"

import subprocess
import tempfile
import shutil
import atexit
import os.path
import os
import hashlib
import fitz
import IPython.display
import html
import base64
import numbers


class cfg:
    "configuration variables"

    display_dpi = 96    # standard monitor dpi
    file_dpi = 300

    # executable name, possibly including path
    # pdflatex is fastest, lualatex + 50%, xelatex + 100%
    latex = 'pdflatex'

    # {0} is replaced by a Base64-encoded PNG image,
    # {1} by TikZ-LaTeX code
    demo_template = '\n'.join([
        '<div style="background-color:#e0e0e0;margin:0">',
        '  <div>',
        '    <img style="max-width:47%;padding:10px;float:left"',
        '      src="data:image/png;base64,{0}">',
        '    <pre',
        '        style="width:47%;margin:0;padding:10px;float:right;'
        + 'white-space:pre-wrap"',
        '        >{1}</pre>',
        '  </div>',
        '  <div style="clear:both"></div>',
        '</div>'])


# units in cm
inch = 2.54
pt = inch / 72.27
bp = inch / 72
mm = 0.1


def _option(key, val):
    """
    helper function for _options
    Transforms single `key=value` pair into string. A value of `True` is
    omitted, an underscore in a key is transformed into a space.
    """
    key = str(key).replace('_', ' ')
    if val is True:
        return key
    else:
        return f'{key}={str(val)}'


def _options(options=None, **kwoptions):
    """
    helper function to format options in various functions
    Transforms dictionary from Python dictionary / **kwargs into TikZ string,
    e.g. `(options='red', thick=True, rounded_corners='4pt')`
    returns `'[thick,rounded corners=4pt,red]'`.
    """
    o = [_option(key, val) for key, val in kwoptions.items()]
    if options is not None:
        o.insert(0, options)
    code = '[' + ','.join(o) + ']'
    if code == '[]':
        code = ''
    return code


# coordinates

def _point(point):
    """
    helper function for _points and others
    Enables specification of a point as a tuple, list, or np.array of numbers,
    as well as a string like '(a)' or '(3mm,0mm)'.
    """
    # Haven't found a good solution for prefixes, '+', '++'.
    if isinstance(point, str):
        return point
    else:
        return '(' + ','.join(map(str, point)) + ')'


def cycle():
    "cycle 'coordinate'"
    return 'cycle'


def polar(angle, radius, y_radius=None):
    "polar coordinates"
    code = '(' + str(angle) + ':' + str(radius)
    if y_radius is not None:
        code += ' and ' + str(y_radius)
    code += ')'
    return code


def vertical(point1, point2):
    "perpendicular coordinates, vertical"
    coord = _point(point1)
    if coord.startswith('(') and coord.endswith(')'):
        coord = coord[1:-1]
    code = '(' + coord + ' |- '
    coord = _point(point2)
    if coord.startswith('(') and coord.endswith(')'):
        coord = coord[1:-1]
    code += coord + ')'
    return code


def horizontal(point1, point2):
    "perpendicular coordinates, horizontal"
    coord = _point(point1)
    if coord.startswith('(') and coord.endswith(')'):
        coord = coord[1:-1]
    code = '(' + coord + ' -| '
    coord = _point(point2)
    if coord.startswith('(') and coord.endswith(')'):
        coord = coord[1:-1]
    code += coord + ')'
    return code


# path operations


def _points(points):
    "helper function for path operations"
    # detect if only a single point was given
    if isinstance(points, str) or isinstance(points[0], numbers.Number):
        # transform into one-element sequence of points
        points = [points]
    # ensure correct representation of points
    points = [_point(p) for p in points]
    return points


def moveto(points):
    "move-to operation"
    # put move-to operation before each point
    # (implicit at the beginning)
    return f' '.join(_points(points))


def lineto(points, op='--'):
    """
    line-to operation
    op can be
    '--' for straight lines (default),
    '-|' for first horizontal, then vertical, or
    '|-' for first vertical, then horizontal
    """
    # put line-to operation before each point
    return f'{op} ' + f' {op} '.join(_points(points))


def line(points, op='--'):
    """
    convenience version of lineto
    starts with move-to instead of line-to operation
    """
    return f' {op} '.join(_points(points))


def curveto(point, control1, control2=None):
    "curve-to operation"
    code = '.. controls ' + _point(control1)
    if control2 is not None:
        code += ' and ' + _point(control2)
    code += ' ..' + ' ' + _point(point)
    return code


def rectangle(point, options=None, **kwoptions):
    "rectangle operation"
    code = 'rectangle' + _options(options=options, **kwoptions)
    code += ' ' + _point(point)
    return code


def circle(options=None, **kwoptions):
    "circle operation (also for ellipses)"
    return 'circle' + _options(options=options, **kwoptions)


def arc(options=None, **kwoptions):
    "arc operation"
    return 'arc' + _options(options=options, **kwoptions)


def grid(point, options=None, **kwoptions):
    "grid operation"
    code = 'grid' + _options(options=options, **kwoptions)
    code += ' ' + _point(point)
    return code


def parabola(point, bend=None, options=None, **kwoptions):
    "parabola operation"
    code = 'parabola' + _options(options=options, **kwoptions)
    if bend is not None:
        code += ' bend ' + _point(bend)
    code += ' ' + _point(point)
    return code


def sin(point, options=None, **kwoptions):
    "sine operation"
    code = 'sin' + _options(options=options, **kwoptions)
    code += ' ' + _point(point)
    return code


def cos(point, options=None, **kwoptions):
    "cosine operation"
    code = 'cos' + _options(options=options, **kwoptions)
    code += ' ' + _point(point)
    return code


# more operations to follow


# environments


class Scope:
    "representation of `scope` environment"

    def __init__(self, options=None, **kwoptions):
        self.elements = []
        self.options = _options(options=options, **kwoptions)

    def add(self, el):
        "add element (may be string)"
        self.elements.append(el)

    def scope(self):
        "scope environment"
        s = Scope()
        self.add(s)
        return s

    def __str__(self):
        "create LaTeX code"
        code = r'\begin{scope}' + self.options + '\n'
        code += '\n'.join(map(str, self.elements)) + '\n'
        code += r'\end{scope}'
        return code

    # commands

    def path(self, *spec, options=None, **kwoptions):
        "path command"
        self.add(r'\path'
                 + _options(options=options, **kwoptions) + ' '
                 + moveto(spec) + ';')

    def draw(self, *spec, options=None, **kwoptions):
        "draw command"
        self.add(r'\draw'
                 + _options(options=options, **kwoptions) + ' '
                 + moveto(spec) + ';')

    def fill(self, *spec, options=None, **kwoptions):
        "fill command"
        self.add(r'\fill'
                 + _options(options=options, **kwoptions) + ' '
                 + moveto(spec) + ';')

    def filldraw(self, *spec, options=None, **kwoptions):
        "filldraw command"
        self.add(r'\filldraw'
                 + _options(options=options, **kwoptions) + ' '
                 + moveto(spec) + ';')

    def clip(self, *spec, options=None, **kwoptions):
        "clip command"
        self.add(r'\clip'
                 + _options(options=options, **kwoptions) + ' '
                 + moveto(spec) + ';')

    def shade(self, *spec, options=None, **kwoptions):
        "shade command"
        self.add(r'\shade'
                 + _options(options=options, **kwoptions) + ' '
                 + moveto(spec) + ';')

    def shadedraw(self, *spec, options=None, **kwoptions):
        "shadedraw command"
        self.add(r'\shadedraw'
                 + _options(options=options, **kwoptions) + ' '
                 + moveto(spec) + ';')

    # more commands to follow


class Picture(Scope):
    "representation of `tikzpicture` environment"

    def __init__(self, options=None, **kwoptions):
        super().__init__(options=options, **kwoptions)
        # additional preamble entries
        self.preamble = []
        # create temporary directory for pdflatex etc.
        self.tempdir = tempfile.mkdtemp(prefix='tikz-')
        # make sure it gets deleted
        atexit.register(shutil.rmtree, self.tempdir, ignore_errors=True)

    def usetikzlibrary(self, library):
        "usetikzlibrary"
        self.preamble.append(r'\usetikzlibrary{' + library + '}')

    def __str__(self):
        "create LaTeX code"
        # We use `str` to create the LaTeX code so that we can directly include
        # strings in `self.elements`, for which `str()` is idempotent.
        code = r'\begin{tikzpicture}' + self.options + '\n'
        code += '\n'.join(map(str, self.elements)) + '\n'
        code += r'\end{tikzpicture}'
        return code

    def _create_pdf(self):
        "ensure that an up-to-date PDF file exists"

        sep = os.path.sep

        # We don't want a PDF file of the whole LaTeX document, but only of the
        # contents of the `tikzpicture` environment. This is achieved using
        # TikZ' `external` library, which makes TikZ write out pictures as
        # individual PDF files. To do so, in a normal pdflatex run TikZ calls
        # pdflatex again with special arguments. We use these special
        # arguments directly. See section 53 of the PGF/TikZ manual.

        # create LaTeX code
        code = (
            '\n'.join([
                r'\documentclass{article}',
                r'\usepackage{tikz}',
                r'\usetikzlibrary{external}',
                r'\tikzexternalize'])
            + '\n'.join(self.preamble) + '\n'
            + r'\begin{document}' + '\n'
            + str(self) + '\n'
            + r'\end{document}' + '\n')
        # print(code)

        # does the PDF file have to be created?
        #  This check is implemented by using the SHA1 digest of the LaTeX code
        # in the PDF filename, and to skip creation if that file exists.
        hash = hashlib.sha1(code.encode()).hexdigest()
        self.temp_pdf = self.tempdir + sep + 'tikz-' + hash + '.pdf'
        if os.path.isfile(self.temp_pdf):
            return

        # create LaTeX file
        temp_tex = self.tempdir + sep + 'tikz.tex'
        with open(temp_tex, 'w') as f:
            f.write(code)

        # process LaTeX file into PDF
        completed = subprocess.run(
            [cfg.latex,
             '-jobname',
             'tikz-figure0',
             r'\def\tikzexternalrealjob{tikz}\input{tikz}'],
            cwd=self.tempdir,
            capture_output=True,
            text=True)
        if completed.returncode != 0:
            raise LatexException('pdflatex has failed\n' + completed.stdout)

        # rename created PDF file
        os.rename(self.tempdir + sep + 'tikz-figure0.pdf', self.temp_pdf)

    def write_image(self, filename, dpi=None):
        "write picture to image file (PDF, PNG, or SVG)"
        if dpi is None:
            dpi = cfg.file_dpi
        self._create_pdf()
        # determine extension
        _, ext = os.path.splitext(filename)
        # if a PDF is requested,
        if ext.lower() == '.pdf':
            # just copy the file
            shutil.copyfile(self.temp_pdf, filename)
        elif ext.lower() == '.png':
            # render PDF as PNG using PyMuPDF
            zoom = dpi / 72
            doc = fitz.open(self.temp_pdf)
            page = doc.loadPage(0)
            pix = page.getPixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
            pix.writePNG(filename)
        elif ext.lower() == '.svg':
            # convert PDF to SVG using PyMuPDF
            doc = fitz.open(self.temp_pdf)
            page = doc.loadPage(0)
            svg = page.getSVGimage()
            with open(filename, 'w') as f:
                f.write(svg)
        else:
            print(f'format {ext[1:]} is not supported')

    def _repr_png_(self):
        "represent of picture as PNG for notebook"
        self._create_pdf()
        # render PDF as PNG using PyMuPDF
        zoom = cfg.display_dpi / 72
        doc = fitz.open(self.temp_pdf)
        page = doc.loadPage(0)
        pix = page.getPixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.getPNGdata()

    def demo(self):
        "convenience function to test & debug picture"
        png_base64 = ''
        try:
            png_base64 = base64.b64encode(self._repr_png_()).decode('ascii')
        except LatexException as le:
            message = le.args[0]
            tikz_error = message.find('! ')
            if tikz_error != -1:
                message = message[tikz_error:]
            print(message)
        code_escaped = html.escape(str(self))
        IPython.display.display(IPython.display.HTML(
            cfg.demo_template.format(png_base64, code_escaped)))


class LatexException(Exception):
    "problem with external LaTeX process"
    pass


# create pytikz logo
if __name__ == "__main__":
    pic = Picture()
    pic.add(r'\draw[darkgray] (0,0) node[scale=2] {\textsf{py}Ti\emph{k}Z};')
    pic.write_image('pytikz.png')
