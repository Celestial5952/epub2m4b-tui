#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
readonly repo_root
readonly expected_os="26.04"

skip_tests=false
if [[ "${1:-}" == "--skip-tests" ]]; then
    skip_tests=true
    shift
fi
if (( $# != 0 )); then
    echo "Usage: packaging/debian/build.sh [--skip-tests]" >&2
    exit 2
fi

if [[ -r /etc/os-release ]]; then
    # shellcheck source=/dev/null
    . /etc/os-release
else
    echo "Cannot identify the build operating system." >&2
    exit 1
fi

if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "${expected_os}" ]]; then
    echo "Release packages must be built on Ubuntu ${expected_os}; found ${PRETTY_NAME:-unknown}." >&2
    exit 1
fi

if [[ -n "${EPUB2M4B_BUILD_PYTHON:-}" ]]; then
    build_python="${EPUB2M4B_BUILD_PYTHON}"
elif [[ -x "${repo_root}/.venv/bin/python" ]]; then
    build_python="${repo_root}/.venv/bin/python"
else
    build_python="python3"
fi
readonly build_python
for executable in "${build_python}" dpkg dpkg-deb install sed du gzip find chmod; do
    if ! command -v "${executable}" >/dev/null 2>&1; then
        echo "Required build command is missing: ${executable}" >&2
        exit 1
    fi
done

python_version="$(${build_python} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
readonly python_version
if [[ "${python_version}" != "3.14" ]]; then
    echo "Release packages require Python 3.14; found ${python_version}." >&2
    exit 1
fi

version="$(${build_python} -c "import pathlib, tomllib; print(tomllib.loads(pathlib.Path('${repo_root}/pyproject.toml').read_text())['project']['version'])")"
readonly version
architecture="$(dpkg --print-architecture)"
readonly architecture
if [[ "${architecture}" != "amd64" ]]; then
    echo "The current release target is amd64; found ${architecture}." >&2
    exit 1
fi

if [[ "${skip_tests}" == false ]]; then
    (cd -- "${repo_root}" && "${build_python}" -m pytest -q)
fi

build_root="$(mktemp -d -t epub2m4b-package.XXXXXXXX)"
readonly build_root
cleanup() {
    rm -rf -- "${build_root}"
}
trap cleanup EXIT

readonly package_root="${build_root}/epub2m4b_${version}_${architecture}"
readonly app_root="${package_root}/usr/lib/epub2m4b"
readonly output_dir="${repo_root}/dist"
readonly artifact="${output_dir}/epub2m4b_${version}_${architecture}.deb"

install -d \
    "${package_root}/DEBIAN" \
    "${package_root}/usr/bin" \
    "${app_root}" \
    "${package_root}/usr/share/applications" \
    "${package_root}/usr/share/icons/hicolor/scalable/apps" \
    "${package_root}/usr/share/doc/epub2m4b" \
    "${output_dir}"

"${build_python}" -m pip install \
    --disable-pip-version-check \
    --no-compile \
    --requirement "${script_dir}/requirements.lock" \
    --target "${app_root}"

cp -a -- "${repo_root}/src/epub2m4b" "${app_root}/epub2m4b"
# The checkout carries development bytecode that must not ship in the package.
find "${app_root:?}/epub2m4b" -type d -name __pycache__ -exec rm -rf -- {} +
# Console scripts from wheels point at the build machine's interpreter and are
# unused by the isolated launcher; drop them instead of shipping broken shebangs.
rm -rf -- "${app_root:?}/bin"
# Wheels and pip leave group-writable trees; Debian expects root:root 0755/0644.
chmod -R u+rwX,go+rX,go-w "${package_root}/usr"
find "${package_root}/usr" -type d -exec chmod 0755 -- {} +
find "${package_root}/usr" -type f -exec chmod 0644 -- {} +
install -m 0644 "${script_dir}/launcher.py" "${app_root}/launcher.py"
install -m 0755 "${script_dir}/epub2m4b" "${package_root}/usr/bin/epub2m4b"
install -m 0644 \
    "${repo_root}/resources/desktop/epub2m4b.desktop" \
    "${package_root}/usr/share/applications/epub2m4b.desktop"
install -m 0644 \
    "${repo_root}/resources/icons/hicolor/scalable/apps/epub2m4b.svg" \
    "${package_root}/usr/share/icons/hicolor/scalable/apps/epub2m4b.svg"
install -m 0644 "${repo_root}/README.md" "${package_root}/usr/share/doc/epub2m4b/README.md"
gzip -n -9 -c "${repo_root}/CHANGELOG.md" >"${package_root}/usr/share/doc/epub2m4b/NEWS.gz"
gzip -n -9 -c "${script_dir}/changelog" >"${package_root}/usr/share/doc/epub2m4b/changelog.gz"
chmod 0644 \
    "${package_root}/usr/share/doc/epub2m4b/NEWS.gz" \
    "${package_root}/usr/share/doc/epub2m4b/changelog.gz"
install -m 0644 "${script_dir}/copyright" "${package_root}/usr/share/doc/epub2m4b/copyright"
install -d -m 0755 "${package_root}/usr/share/man"
install -d -m 0755 "${package_root}/usr/share/man/man1"
gzip -n -9 -c "${script_dir}/epub2m4b.1" >"${package_root}/usr/share/man/man1/epub2m4b.1.gz"
chmod 0644 "${package_root}/usr/share/man/man1/epub2m4b.1.gz"

installed_size="$(du -sk "${package_root}/usr" | awk '{print $1}')"
readonly installed_size
sed \
    -e "s/@VERSION@/${version}/g" \
    -e "s/@ARCHITECTURE@/${architecture}/g" \
    -e "s/@INSTALLED_SIZE@/${installed_size}/g" \
    "${script_dir}/control.in" >"${package_root}/DEBIAN/control"

dpkg-deb --root-owner-group --build "${package_root}" "${artifact}"
dpkg-deb --info "${artifact}"
echo "Built ${artifact}"
