CC = gcc
CFLAGS = -std=c99 -Wall -Wextra

all: test_json

test_json: test_json.c json.h
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f test_json

.PHONY: all clean