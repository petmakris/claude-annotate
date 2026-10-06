# Vendored

`elk.bundled.js` — the Eclipse Layout Kernel, JavaScript build, from npm
`elkjs@0.9.3`. Vendored rather than depended on so the plugin installs with no
package step; `elk_driver.mjs` is the only thing that loads it.

Upgrade: `npm pack elkjs@<version>`, copy `package/lib/elk.bundled.js` here,
run `python3 -m pytest skills/annotate/tests/test_elk_driver.py -q`.

Licence: EPL-2.0, see `ELK_LICENSE.txt`.
