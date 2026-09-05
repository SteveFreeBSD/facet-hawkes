#!/usr/bin/bash
set -euo pipefail

readonly PROJECT_DIR="/home/steve/apps/ethnos"
readonly UV_BIN="/usr/bin/uv"
readonly DOCUMENT_ID="3"
readonly EXTRACTION_MODEL="qwen3.5:9b"

cd "$PROJECT_DIR"

"$UV_BIN" run ethnos structure "$DOCUMENT_ID" \
  --model "$EXTRACTION_MODEL" --all-roles

for retry_number in 1 2 3 4; do
  echo "Precalculus failed-chunk retry ${retry_number}/4"
  "$UV_BIN" run ethnos structure "$DOCUMENT_ID" \
    --model "$EXTRACTION_MODEL" --retry-failed --all-roles \
    --num-predict 4096 --num-ctx 8192
done

"$UV_BIN" run ethnos refresh-records "$DOCUMENT_ID"
"$UV_BIN" run ethnos section-status "$DOCUMENT_ID"
"$UV_BIN" run ethnos structure-status "$DOCUMENT_ID"
"$UV_BIN" run ethnos quality-report "$DOCUMENT_ID"
