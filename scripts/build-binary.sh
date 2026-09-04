#!/usr/bin/env bash
# Build a Linux x86_64 binary with PyInstaller (onedir) and pack a tarball.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c "from linuxdiskinfo import __version__; print(__version__)")"
ARCH="$(uname -m)"
NAME="linuxdiskinfo-${VERSION}-linux-${ARCH}"

if [[ -x "${ROOT}/.venv/bin/pyinstaller" ]]; then
  PYINSTALLER="${ROOT}/.venv/bin/pyinstaller"
else
  PYINSTALLER="pyinstaller"
fi

rm -rf "${ROOT}/build" "${ROOT}/dist/linuxdiskinfo" "${ROOT}/dist/${NAME}" "${ROOT}/dist/${NAME}.tar.gz"

"${PYINSTALLER}" \
  --noconfirm \
  --clean \
  --workpath "${ROOT}/build" \
  --distpath "${ROOT}/dist" \
  "${ROOT}/packaging/linuxdiskinfo.spec"

STAGE="${ROOT}/dist/${NAME}"
mkdir -p "${STAGE}"
cp -a "${ROOT}/dist/linuxdiskinfo/." "${STAGE}/"
cp "${ROOT}/README.md" "${ROOT}/LICENSE" "${STAGE}/"
mkdir -p "${STAGE}/share/applications" "${STAGE}/share/icons/hicolor/scalable/apps"
cp "${ROOT}/data/linuxdiskinfo.desktop" "${STAGE}/share/applications/"
cp "${ROOT}/data/icons/hicolor/scalable/apps/linuxdiskinfo.svg" \
  "${STAGE}/share/icons/hicolor/scalable/apps/"

# Wrapper: prefer the bundled binary from any cwd.
cat > "${STAGE}/linuxdiskinfo.sh" << 'EOF'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/linuxdiskinfo" "$@"
EOF
chmod +x "${STAGE}/linuxdiskinfo.sh" "${STAGE}/linuxdiskinfo"

tar -C "${ROOT}/dist" -czf "${ROOT}/dist/${NAME}.tar.gz" "${NAME}"
echo "Built ${ROOT}/dist/${NAME}.tar.gz"
