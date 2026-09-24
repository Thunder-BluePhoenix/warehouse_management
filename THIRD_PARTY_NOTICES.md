The Warehouse 3D feature (api/warehouse_3d*.py, public/js/warehouse_3d.js, the warehouse-3d page/www route,
the Warehouse UOM Capacity doctype and the wt_* Warehouse custom fields) is derived from
Warehouse Theatre 3D by Aravind G, used under the MIT License below.

MIT License

Copyright (c) 2026 Aravind G

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


---

## Bundled libraries (public/js/lib/)

- **three.js r128** (`three.r128.min.js`), Copyright 2010-2021 Three.js Authors, MIT License. https://github.com/mrdoob/three.js
- **Vue 3.5.13** (`vue.3.5.13.global.prod.js`), Copyright (c) 2018-present Yuxi (Evan) You and Vue contributors, MIT License. https://github.com/vuejs/core

Both are unmodified upstream builds (sha256 in the commit that added them), served from /assets so the app works without CDN access.
