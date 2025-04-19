Convert HTML to EPUB
====================

This repo contains a Python script that converts a provided HTML file to the EPUB ebook format.

This is a fairly straightforward task because [EPUB is basically a wrapper around HTML](https://en.wikipedia.org/wiki/EPUB#Implementation), but I was surprised that I couldn't find any existing code to do this when I needed it.

This code was written entirely by an LLM and may not work for your inputs. It seemed to work fine for me, however.


Running
-------

The script has no external dependencies and should work with any reasonably recent version of Python 3.
You can run it with:

```sh
python3 convert_html_to_epub.py your_input_file.html
```

If you have [uv](https://docs.astral.sh/uv/), you can even run it without downloading:

```sh
uv run --script https://raw.githubusercontent.com/nmalkin/convert_html_to_epub/refs/heads/master/convert_html_to_epub.py your_input_file.html
```

