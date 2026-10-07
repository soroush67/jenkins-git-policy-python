#!/usr/bin/env bash
# Create sample files that trigger each rule type, in ./out (or $1).
set -euo pipefail
out=${1:-$(dirname "$0")/out}
mkdir -p "$out"
head -c 2048 /dev/urandom > "$out/random.bin"                                  # binary_files
printf '\x7fELF\x02\x01\x01\x00' > "$out/fake-elf"; head -c 512 /dev/zero >> "$out/fake-elf"
printf 'MZ\x90\x00' > "$out/setup.exe"                                         # forbidden_extensions + binary
echo "just text, but a forbidden extension" > "$out/library.dll"              # forbidden_extensions
echo "DB_PASSWORD=secret" > "$out/.env"                                        # forbidden_paths
printf 'aws_key = "AKIA%s"\n' "ABCDEFGHIJKLMNOP" > "$out/config.py"            # secret_patterns
head -c $((12*1024*1024)) /dev/zero | tr '\0' 'a' > "$out/big.txt"             # max_file_size (12 MB of text)
echo "hello" > "$out/ok.txt"                                                   # allowed
ls -la "$out"
