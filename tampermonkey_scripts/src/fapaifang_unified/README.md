# Unified userscript source layout

`fapaifang_unified.user.js` must remain one installable Tampermonkey file so its
metadata, grants, load order, and shared IIFE state do not change. The numbered
JavaScript fragments in this directory are the maintained source, in manifest
order. Some fragments intentionally begin or end inside the shared IIFE and are
not standalone scripts.

The fragments retain legacy line-ending whitespace where needed to reproduce
the unchanged installable file exactly. The local `.gitattributes` exception is
limited to these generated-output source slices; other Crow source keeps the
repository's normal whitespace checks.

Verify that the tracked installable output is current:

```powershell
node scripts/build-userscript.mjs --check
```

Rebuild it after editing a fragment:

```powershell
node scripts/build-userscript.mjs --write
node --check tampermonkey_scripts/fapaifang_unified.user.js
```

An intentional behavior change must also update the reviewed source hash in
`scripts/tests/build-userscript.test.mjs` as an explicit review checkpoint.
