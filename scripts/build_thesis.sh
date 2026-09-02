#!/usr/bin/env bash
# Build the thesis PDF with TinyTeX/TeX Live (pdflatex + biber).
# Usage: scripts/build_thesis.sh [--clean]
set -euo pipefail
cd "$(dirname "$0")/../thesis"

LATEX_BIN=""
for d in "$HOME/.TinyTeX/bin/x86_64-linux" /usr/local/texlive/*/bin/x86_64-linux /usr/bin; do
	if [ -x "$d/pdflatex" ]; then LATEX_BIN="$d"; break; fi
done
if [ -z "$LATEX_BIN" ]; then
	echo "pdflatex not found. Install TinyTeX: wget -qO- https://yihui.org/tinytex/install-bin-unix.sh | sh" >&2
	exit 1
fi
echo "Using LaTeX from: $LATEX_BIN"
export PATH="$LATEX_BIN:$PATH"
# biber is a par-packed binary needing libcrypt.so.1 (GLIBC versioned);
# a user-space compat copy lives in ~/.local/lib
if [ -f "$HOME/.local/lib/libcrypt.so.1" ]; then
	export LD_LIBRARY_PATH="$HOME/.local/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

if [ "${1:-}" = "--clean" ]; then
	rm -f main.aux main.bbl main.bcf main.blg main.log main.lof main.lot main.out main.run.xml main.toc main.synctex.gz
fi

pdflatex -interaction=nonstopmode main.tex >/dev/null
biber main >/dev/null
pdflatex -interaction=nonstopmode main.tex >/dev/null
pdflatex -interaction=nonstopmode main.tex | tail -n 6 || true

PAGES=$(pdfinfo main.pdf 2>/dev/null | awk '/^Pages:/{print $2}' || echo "?")
echo "Build OK -> thesis/main.pdf (${PAGES} pages)"
