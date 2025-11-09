FROM erikvl87/languagetool:latest

USER root
RUN if command -v apt-get >/dev/null; then \
      apt-get update && apt-get install -y --no-install-recommends libhunspell-1.7-0 && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null; then \
      apk add --no-cache hunspell; \
    else \
      echo "No supported package manager found"; exit 1; \
    fi
RUN if [ ! -e /usr/lib/libhunspell.so ] && [ -e /usr/lib/libhunspell-1.7.so.0 ]; then \
      ln -s /usr/lib/libhunspell-1.7.so.0 /usr/lib/libhunspell.so; \
    fi
