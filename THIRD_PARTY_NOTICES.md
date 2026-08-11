# Third-party notices

## tosu

This project bundles and automatically launches **tosu**
(https://github.com/tosuapp/tosu), a memory reader for osu! that exposes
live gameplay data over a local websocket API. All credit for tosu goes to
its authors and contributors - it is not part of this project, and this
project would not be possible without it.

- **Project:** tosu - https://github.com/tosuapp/tosu
- **License:** GNU Lesser General Public License v3.0 (LGPL-3.0) -
  full text at https://github.com/tosuapp/tosu/blob/master/LICENSE
- **What we do with it:** we download tosu's official, unmodified Windows
  release binary and run it as a separate background process purely for
  convenience, so users don't have to install it themselves. We do not
  modify, statically link against, or redistribute modified copies of
  tosu's source or binary. If tosu is already running on your machine
  (e.g. for stream overlays), this project detects that and does not
  start a second copy.
- **Source availability:** tosu's source code is publicly available at
  the repository above, satisfying LGPL-3.0's source-availability
  requirement for the binary we bundle.

If you are the tosu authors and would prefer this project not bundle your
binary, or want the attribution here changed, please open an issue.
