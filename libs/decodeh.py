# encoding: utf-8
# decodeh.py –用于启发性猜测编码方案的算法与模块
# https://web.archive.org/web/20080108123255/http://gizmojo.org/code/decodeh/
import sys
import codecs
import locale
import re


class RoundTripError(UnicodeError):
    pass


UTF_BOMS = [
    (getattr(codecs, 'BOM_UTF8', '\xef\xbb\xbf'), 'utf_8'),
    (getattr(codecs, 'BOM_UTF16_LE', '\xff\xfe'), 'utf_16_le'),  # utf-16
    (getattr(codecs, 'BOM_UTF16_BE', '\xfe\xff'), 'utf_16_be'),
    # (getattr(codecs, 'BOM_UTF32_LE', '\xff\xfe\x00\x00'), 'utf_32_le'), # utf-32
    # (getattr(codecs, 'BOM_UTF32_BE', '\x00\x00\xfe\xff'), 'utf_32_be')
]


def get_bom_encoding(s):
    """ (s:str) -> either((None, None), (bom:str, encoding:str)) """
    for bom, encoding in UTF_BOMS:
        if s.startswith(bom):
            return bom, encoding
    return None, None


def is_lossy(s, enc, x=None):
    """ (s:str, enc:str, x:either(unicode, None)) -> bool
    Return False if a decode/encode roundtrip of byte string s does not lose
    any data. If x is not None, it is expected to be unicode(s, enc).
    Note that this will, incorrectly, return True for cases where the
    encoding is ambiguous, e.g. is_lossy("\x1b(BHallo","iso2022_jp"),
    see comp.lang.python thread "unicode(s, enc).encode(enc) == s ?".
    """
    if x is None:
        x = unicode(s, enc)
    if x.encode(enc) == s:
        return False
    else:
        return True


# may_do_better post-guess checks

def may_do_better(s, encodings, guenc, mdb):
    funcs = mdb.get(guenc)
    if funcs is None:
        return None
    for func in funcs:
        candidenc = func.func_defaults[-1]
        if not candidenc in encodings:
            continue
        if encodings.index(guenc) > encodings.index(candidenc):
            continue
        candidenc = func(s, encodings, guenc)
        if candidenc is not None:
            return candidenc


# latin_1 control chars between 0x80 and 0x9F are displayable in cp1252
def _latin_1_control_chars(s, encodings, guenc="latin_1", candidenc="cp1252"):
    if _latin_1_control_chars.re.search(s) is not None:
        return candidenc


_latin_1_control_chars.re = re.compile(r"[\x80-\x9f]")


# Chars in range below are more likely to be used as symbols in iso8859_15
def _iso8859_15_symbols(s, encodings, guenc="latin_1", candidenc="iso8859_15"):
    # guenc: "latin_1", "cp1252"
    if _iso8859_15_symbols.re.search(s) is not None:
        return candidenc


_iso8859_15_symbols.re = re.compile(r"[\xa4\xa6\xa8\xb4\xb8\xbc-\xbe]")


def _iso2022_jp_escapes(s, encodings, guenc="ascii", candidenc="iso2022_jp"):
    if _iso2022_jp_escapes.re.search(s) is not None:
        return candidenc


_iso2022_jp_escapes.re = re.compile(r"\x1b\(B|\x1b\(J|\x1b\$@|\x1b\$B")

# user specifiable parameters - defaults

# The default list of encodings to try (after "ascii" and "utf_8").
# Order matters! Encoding names use the corresponding python codec name,
# as listed at: http://docs.python.org/lib/standard-encodings.html
ENCS = ["latin_1", "cp1252", "iso8859_15", "mbcs",
        "big5", "euc_jp", "euc_kr", "gb2312", "gbk", "gb18030", "hz",
        "iso2022_jp", "iso2022_jp_1", "iso2022_jp_2", "iso2022_jp_3",
        "iso2022_jp_2004", "iso2022_jp_ext", "iso2022_kr",
        "koi8_u", "ptcp154", "shift_jis"]

# dictionary specifying the may_do_better checks per encoding
MDB = {
    "ascii": [_iso2022_jp_escapes],
    "latin_1": [_latin_1_control_chars, _iso8859_15_symbols],
    "cp1252": [_iso8859_15_symbols],
}


# user callable utilities

def decode_from_file(filename, enc=None, encodings=ENCS, mdb=MDB, lossy=False):
    """ (s:str, enc:str, encodings:list, mdb:dict, lossy:bool) -> x:unicode
    Convenient wrapper on decode(str).
    """
    f = open(filename, 'r')
    s = f.read()
    f.close()
    return decode(s, enc=enc, encodings=encodings, mdb=mdb, lossy=lossy)


def decode(s, enc=None, encodings=ENCS, mdb=MDB, lossy=False):
    """ (s:str, enc:str, encodings:list, mdb:dict, lossy:bool) -> x:unicode
    Raises RoundTripError when lossy=False and re-encoding the string
    is not equal to the input string.
    """
    x, enc, loses = decode_heuristically(s, enc=enc, encodings=encodings, mdb=mdb)
    if not lossy and loses:
        raise RoundTripError("Data loss in decode/encode round trip")
    else:
        return x


def decode_heuristically(s, enc=None, encodings=ENCS, mdb=MDB):
    """ (s:str, enc:str, encodings:list, mdb:dict) ->
                                            (x:unicode, enc:str, lossy:bool)
    Tries to determine the best encoding to use from a list of specified
    encodings, and returns the 3-tuple: a unicode object, the encoding used,
    and whether deleting chars from input was needed to generate a Unicode
    object.
    """
    if isinstance(s, unicode):
        return s, "utf_8", False  # nothing to do
    # A priori, the byte string may be in a UTF encoding and may have a BOM
    # that we may use but that we must also remove.
    bom, bom_enc = get_bom_encoding(s)
    if bom is not None:
        s = s[len(bom):]
    # Order is important: encodings should be in a *most likely* order.
    # Thus, we always try first:
    # a) any caller-provided encoding
    # b) encoding from UTF BOM
    # c) ascii, common case and is unambiguous if no errors
    # d) utf_8
    # e) system default encoding
    # f) any encodings we can glean from the locale
    precedencs = [enc, bom_enc, "ascii", "utf_8", sys.getdefaultencoding()]
    try:
        precedencs.append(locale.getpreferredencoding())
    except AttributeError:
        pass
    try:
        precedencs.append(locale.nl_langinfo(locale.CODESET))
    except AttributeError:
        pass
    try:
        precedencs.append(locale.getlocale()[1])
    except (AttributeError, IndexError):
        pass
    try:
        precedencs.append(locale.getdefaultlocale()[1])
    except (AttributeError, IndexError):
        pass
    # Build list of encodings to process, normalizing on lowercase names
    # and avoiding any None and duplicate values.
    precedencs = [e.lower() for e in precedencs if e is not None]
    allencs = []
    for e in precedencs:
        if e not in allencs:
            allencs.append(e)
    allencs += [e for e in encodings if e not in allencs]
    eliminencs = []
    for enc in allencs:
        try:
            x = unicode(s, enc)
        except (UnicodeError, LookupError), exc:
            eliminencs.append(enc)
            continue
        else:
            candidenc = may_do_better(s, allencs, enc, mdb)
            if candidenc is not None:
                y, yenc, loses = decode_heuristically(s, candidenc, allencs, mdb)
                if not loses:
                    return y, yenc, False
            return x, enc, False
    # no enc worked - try again, using "ignore" parameter, return longest
    if eliminencs:
        allencs = [e for e in allencs if e not in eliminencs]
    output = [(unicode(s, enc, "ignore"), enc) for enc in allencs]
    output = [(len(x[0]), x) for x in output]
    output.sort()
    x, enc = output[-1][1]
    if not is_lossy(s, enc, x):
        return x, enc, False
    else:
        return x, enc, True
