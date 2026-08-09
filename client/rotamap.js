/*!
 * RotaMap v0.1 — tiny rotatable slippy-map library (no dependencies)
 * Leaflet-like API + TRUE map rotation via setBearing(deg).
 * Made for ASV / robotics dashboards where the map must follow heading.
 *
 * Convention:
 *   - bearing = the real-world heading (deg, clockwise from North) that
 *     should appear at the TOP of the screen. bearing 0 => North up.
 *   - Web Mercator projection (same as Leaflet/OSM), tile size 256.
 */
(function (global) {
  'use strict';

  var TILE = 256;
  var DEG = Math.PI / 180;
  var R2D = 180 / Math.PI;
  var EARTH_C = 40075016.686; // earth circumference (m) at equator
  var MAX_LAT = 85.05112878;
  var SUBS = ['a', 'b', 'c'];

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  // Accept [lat,lng] or {lat,lng} -> {lat,lng}
  function LL(x) {
    if (!x) return { lat: 0, lng: 0 };
    if (Array.isArray(x)) return { lat: x[0], lng: x[1] };
    if (typeof x.lng === 'number') return { lat: x.lat, lng: x.lng };
    if (typeof x.lon === 'number') return { lat: x.lat, lng: x.lon };
    return { lat: x.lat, lng: x.lng };
  }

  // ---- Web Mercator (pixel coords for a given zoom) ----
  function project(lat, lng, zoom) {
    var scale = TILE * Math.pow(2, zoom);
    lat = clamp(lat, -MAX_LAT, MAX_LAT);
    var x = (lng + 180) / 360 * scale;
    var s = Math.sin(lat * DEG);
    var y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * scale;
    return { x: x, y: y };
  }
  function unproject(x, y, zoom) {
    var scale = TILE * Math.pow(2, zoom);
    var lng = x / scale * 360 - 180;
    var n = Math.PI - 2 * Math.PI * y / scale;
    var lat = R2D * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
    return { lat: lat, lng: lng };
  }
  function metersPerPixel(lat, zoom) {
    return EARTH_C * Math.cos(lat * DEG) / Math.pow(2, zoom + 8);
  }

  // small DOM helper
  function el(tag, css, parent) {
    var d = document.createElement(tag);
    if (css) d.style.cssText = css;
    if (parent) parent.appendChild(d);
    return d;
  }

  // =====================================================================
  //  MAP
  // =====================================================================
  function RMap(container, opts) {
    opts = opts || {};
    this.container = typeof container === 'string'
      ? document.getElementById(container) : container;
    if (!this.container) throw new Error('RotaMap: container not found');

    this._center = LL(opts.center || [0, 0]);
    this._zoom = opts.zoom != null ? opts.zoom : 13;
    this._bearing = opts.bearing || 0;
    this.minZoom = opts.minZoom != null ? opts.minZoom : 2;
    this.maxZoom = opts.maxZoom != null ? opts.maxZoom : 22;

    this._layers = [];     // tile layers
    this._markers = [];
    this._vectors = [];    // polylines + circles
    this._tiles = {};      // key z/x/y -> img
    this._handlers = {};   // event name -> [fn]
    this._raf = null;

    this._buildDOM();
    this._bindInput();
    this.invalidateSize();

    var self = this;
    this._onResize = function () { self.invalidateSize(); };
    global.addEventListener('resize', this._onResize);
  }

  RMap.prototype._buildDOM = function () {
    var c = this.container;
    if (getComputedStyle(c).position === 'static') c.style.position = 'relative';
    c.style.overflow = 'hidden';
    c.style.touchAction = 'none';
    c.style.background = '#e8e8e8';

    // rotating pane: zero-size point pinned at container center.
    // Everything (tiles, vectors, markers) is positioned relative to its
    // origin (0,0 == container center) and rotates together.
    this._pane = el('div',
      'position:absolute;left:50%;top:50%;width:0;height:0;' +
      'transform-origin:0 0;will-change:transform;', c);

    this._tilePane = el('div', 'position:absolute;left:0;top:0;', this._pane);

    var OFF = this._svgOff = 8000;
    this._svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this._svg.setAttribute('width', OFF * 2);
    this._svg.setAttribute('height', OFF * 2);
    this._svg.style.cssText =
      'position:absolute;left:' + (-OFF) + 'px;top:' + (-OFF) + 'px;' +
      'overflow:visible;pointer-events:none;';
    this._pane.appendChild(this._svg);

    this._markerPane = el('div', 'position:absolute;left:0;top:0;', this._pane);

    // non-rotating overlay (for popups that stay upright & screen-fixed)
    this._popupPane = el('div',
      'position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none;', c);
  };

  // ---- coordinate transforms (world <-> screen, accounting for bearing) ----
  RMap.prototype._screenOf = function (worldX, worldY) {
    var W = this._w, H = this._h, B = this._bearing * DEG;
    var vx = worldX - this._wc.x, vy = worldY - this._wc.y;
    var cos = Math.cos(B), sin = Math.sin(B);
    return {
      x: vx * cos + vy * sin + W / 2,
      y: -vx * sin + vy * cos + H / 2
    };
  };
  RMap.prototype._worldOf = function (sx, sy) {
    var W = this._w, H = this._h, B = this._bearing * DEG;
    var dx = sx - W / 2, dy = sy - H / 2;
    var cos = Math.cos(B), sin = Math.sin(B);
    return {
      x: this._wc.x + (dx * cos - dy * sin),
      y: this._wc.y + (dx * sin + dy * cos)
    };
  };

  // Public projection helpers (Leaflet-ish)
  RMap.prototype.latLngToContainerPoint = function (latlng) {
    var ll = LL(latlng), w = project(ll.lat, ll.lng, this._zoom);
    return this._screenOf(w.x, w.y);
  };
  RMap.prototype.containerPointToLatLng = function (pt) {
    var w = this._worldOf(pt.x, pt.y);
    return unproject(w.x, w.y, this._zoom);
  };

  // ---- getters / setters ----
  RMap.prototype.getCenter = function () { return { lat: this._center.lat, lng: this._center.lng }; };
  RMap.prototype.getZoom = function () { return this._zoom; };
  RMap.prototype.getBearing = function () { return this._bearing; };

  RMap.prototype.setView = function (center, zoom) {
    this._center = LL(center);
    if (zoom != null) this._zoom = clamp(zoom, this.minZoom, this.maxZoom);
    this._schedule(); this._fire('move'); this._fire('zoom');
    return this;
  };
  RMap.prototype.panTo = function (center) {
    this._center = LL(center); this._schedule(); this._fire('move'); return this;
  };
  RMap.prototype.setZoom = function (zoom) {
    this._zoom = clamp(zoom, this.minZoom, this.maxZoom);
    this._schedule(); this._fire('zoom'); return this;
  };
  RMap.prototype.setBearing = function (deg) {
    this._bearing = ((deg % 360) + 360) % 360;
    this._schedule(); this._fire('rotate'); return this;
  };

  RMap.prototype.invalidateSize = function () {
    this._w = this.container.clientWidth;
    this._h = this.container.clientHeight;
    this._schedule();
    return this;
  };

  // event bus
  RMap.prototype.on = function (name, fn) {
    (this._handlers[name] = this._handlers[name] || []).push(fn); return this;
  };
  RMap.prototype.off = function (name, fn) {
    var a = this._handlers[name]; if (!a) return this;
    this._handlers[name] = a.filter(function (f) { return f !== fn; }); return this;
  };
  RMap.prototype._fire = function (name, data) {
    (this._handlers[name] || []).forEach(function (f) { f(data); });
  };

  // ---- render scheduling ----
  RMap.prototype._schedule = function () {
    if (this._raf) return;
    var self = this;
    this._raf = global.requestAnimationFrame(function () {
      self._raf = null; self._render();
    });
  };

  RMap.prototype._render = function () {
    if (!this._w) this.invalidateSize();
    this._wc = project(this._center.lat, this._center.lng, this._zoom);
    this._pane.style.transform = 'rotate(' + (-this._bearing) + 'deg)';
    this._renderTiles();
    this._renderVectors();
    this._renderMarkers();
    this._renderPopups();
  };

  RMap.prototype._renderTiles = function () {
    var layer = this._layers[0];
    if (!layer) return;
    var z = Math.round(this._zoom);
    var n = Math.pow(2, z);
    var scaleDiff = Math.pow(2, this._zoom - z); // fractional-zoom support
    var half = Math.hypot(this._w, this._h) / 2 + TILE;

    var minWX = this._wc.x - half, maxWX = this._wc.x + half;
    var minWY = this._wc.y - half, maxWY = this._wc.y + half;
    // convert world px (at fractional zoom) to integer-zoom tile px
    var f = 1 / scaleDiff;
    var minTX = Math.floor(minWX * f / TILE), maxTX = Math.floor(maxWX * f / TILE);
    var minTY = Math.floor(minWY * f / TILE), maxTY = Math.floor(maxWY * f / TILE);

    var seen = {}, self = this;
    var size = TILE * scaleDiff;
    for (var tx = minTX; tx <= maxTX; tx++) {
      for (var ty = minTY; ty <= maxTY; ty++) {
        if (ty < 0 || ty >= n) continue;
        var wx = ((tx % n) + n) % n;
        var key = z + '/' + wx + '/' + ty;
        seen[key] = true;
        var left = tx * TILE * scaleDiff - this._wc.x;
        var top = ty * TILE * scaleDiff - this._wc.y;
        var img = this._tiles[key];
        if (!img) {
          img = el('img',
            'position:absolute;width:' + Math.ceil(size) + 'px;height:' +
            Math.ceil(size) + 'px;user-select:none;', this._tilePane);
          img.draggable = false;
          img.src = layer._url(wx, ty, z);
          this._tiles[key] = img;
        } else {
          img.style.width = img.style.height = Math.ceil(size) + 'px';
        }
        img.style.left = left + 'px';
        img.style.top = top + 'px';
      }
    }
    // prune stale tiles
    for (var k in this._tiles) {
      if (!seen[k]) { this._tilePane.removeChild(this._tiles[k]); delete this._tiles[k]; }
    }
  };

  RMap.prototype._renderVectors = function () {
    var OFF = this._svgOff, self = this;
    this._vectors.forEach(function (v) { v._draw(self, OFF); });
  };

  RMap.prototype._renderMarkers = function () {
    var self = this;
    this._markers.forEach(function (m) {
      var w = project(m._ll.lat, m._ll.lng, self._zoom);
      m._outer.style.left = (w.x - self._wc.x) + 'px';
      m._outer.style.top = (w.y - self._wc.y) + 'px';
      // inner angle: keepUpright cancels pane(-bearing); heading marker uses true heading
      var ang = m._keepUpright ? self._bearing : m._rotation;
      var t = 'rotate(' + ang + 'deg)';
      if (m._sizeMeters) {
        // real-world size: pixels = meters / (meters-per-pixel), clamped, then scaled from base px
        var px = m._sizeMeters / metersPerPixel(m._ll.lat, self._zoom);
        px = clamp(px, m._minSizePx, m._maxSizePx);
        t += ' scale(' + (px / m._icon.size[0]) + ')';
      }
      m._inner.style.transform = t;
    });
  };

  RMap.prototype._renderPopups = function () {
    var self = this;
    this._markers.forEach(function (m) {
      if (!m._popupEl || !m._popupOpen) return;
      var p = self.latLngToContainerPoint(m._ll);
      m._popupEl.style.left = p.x + 'px';
      m._popupEl.style.top = p.y + 'px';
    });
  };

  // ---- input: drag-pan, wheel-zoom, click ----
  RMap.prototype._bindInput = function () {
    var self = this, dragging = false, lx = 0, ly = 0, moved = 0;
    var c = this.container;

    c.addEventListener('pointerdown', function (e) {
      dragging = true; moved = 0; lx = e.clientX; ly = e.clientY;
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      var dx = e.clientX - lx, dy = e.clientY - ly;
      lx = e.clientX; ly = e.clientY; moved += Math.abs(dx) + Math.abs(dy);
      var B = self._bearing * DEG, cos = Math.cos(B), sin = Math.sin(B);
      // world shift = -M^-1 * screenDelta
      self._wc.x -= (dx * cos - dy * sin);
      self._wc.y -= (dx * sin + dy * cos);
      self._center = unproject(self._wc.x, self._wc.y, self._zoom);
      self._schedule(); self._fire('move');
    });
    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      try { c.releasePointerCapture(e.pointerId); } catch (_) {}
    }
    c.addEventListener('pointerup', function (e) {
      var wasClick = moved < 4;
      endDrag(e);
      if (wasClick) {
        var r = c.getBoundingClientRect();
        var ll = self.containerPointToLatLng({ x: e.clientX - r.left, y: e.clientY - r.top });
        self._fire('click', { latlng: ll });
      }
    });
    c.addEventListener('pointercancel', endDrag);

    c.addEventListener('wheel', function (e) {
      e.preventDefault();
      var r = c.getBoundingClientRect();
      var pt = { x: e.clientX - r.left, y: e.clientY - r.top };
      var ll = self.containerPointToLatLng(pt);
      var nz = clamp(self._zoom + (e.deltaY < 0 ? 1 : -1), self.minZoom, self.maxZoom);
      if (nz === self._zoom) return;
      self._zoom = nz;
      // keep ll anchored under cursor
      var wll = project(ll.lat, ll.lng, nz);
      var B = self._bearing * DEG, cos = Math.cos(B), sin = Math.sin(B);
      var dx = pt.x - self._w / 2, dy = pt.y - self._h / 2;
      var vx = dx * cos - dy * sin, vy = dx * sin + dy * cos;
      self._wc = { x: wll.x - vx, y: wll.y - vy };
      self._center = unproject(self._wc.x, self._wc.y, nz);
      self._schedule(); self._fire('zoom');
    }, { passive: false });
  };

  RMap.prototype.remove = function () {
    global.removeEventListener('resize', this._onResize);
    this.container.innerHTML = '';
  };

  // =====================================================================
  //  TILE LAYER
  // =====================================================================
  function TileLayer(urlTemplate, opts) {
    this._tpl = urlTemplate;
    this.opts = opts || {};
  }
  TileLayer.prototype._url = function (x, y, z) {
    var s = SUBS[(x + y) % SUBS.length];
    return this._tpl
      .replace('{s}', s).replace('{z}', z).replace('{x}', x).replace('{y}', y);
  };
  TileLayer.prototype.addTo = function (map) {
    map._layers.push(this); map._schedule(); return this;
  };

  // =====================================================================
  //  ICON
  // =====================================================================
  function DivIcon(opts) {
    opts = opts || {};
    this.html = opts.html || '';
    this.size = opts.iconSize || [16, 16];
    this.anchor = opts.iconAnchor || [this.size[0] / 2, this.size[1] / 2];
    this.className = opts.className || '';
  }

  // =====================================================================
  //  MARKER
  // =====================================================================
  function Marker(latlng, opts) {
    opts = opts || {};
    this._ll = LL(latlng);
    this._icon = opts.icon || new DivIcon({
      html: '<div style="width:14px;height:14px;border-radius:50%;background:#0172BB;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)"></div>',
      iconSize: [14, 14]
    });
    this._rotation = opts.rotation || 0;          // true heading (deg), used when keepUpright=false
    this._sizeMeters = opts.sizeMeters || null;   // if set, icon is scaled to real-world size (m)
    this._minSizePx = opts.minSizePx || 0;        // clamp so a tiny real object stays visible/clickable
    this._maxSizePx = opts.maxSizePx || Infinity;
    // default: pixel icons stay upright; meter-sized icons rotate WITH the map (physical objects)
    this._keepUpright = opts.keepUpright != null ? opts.keepUpright : !this._sizeMeters;
    this._map = null;
  }
  Marker.prototype.addTo = function (map) {
    this._map = map;
    var ic = this._icon;
    var outer = el('div',
      'position:absolute;width:0;height:0;', map._markerPane);
    var inner = el('div',
      'position:absolute;left:' + (-ic.anchor[0]) + 'px;top:' + (-ic.anchor[1]) +
      'px;width:' + ic.size[0] + 'px;height:' + ic.size[1] + 'px;' +
      'transform-origin:' + ic.anchor[0] + 'px ' + ic.anchor[1] + 'px;', outer);
    if (ic.className) inner.className = ic.className;
    inner.innerHTML = ic.html;
    inner.style.pointerEvents = 'auto';
    inner.style.cursor = 'pointer';
    this._outer = outer; this._inner = inner;
    var self = this;
    inner.addEventListener('click', function (e) {
      e.stopPropagation();
      if (self._popupContent != null) self.togglePopup();
      self._map._fire('marker-click', { marker: self });
    });
    map._markers.push(this);
    map._schedule();
    return this;
  };
  Marker.prototype.setLatLng = function (latlng) {
    this._ll = LL(latlng); if (this._map) this._map._schedule(); return this;
  };
  Marker.prototype.getLatLng = function () { return { lat: this._ll.lat, lng: this._ll.lng }; };
  Marker.prototype.setRotation = function (deg) {
    this._rotation = deg; this._keepUpright = false;
    if (this._map) this._map._schedule(); return this;
  };
  Marker.prototype.bindPopup = function (html) { this._popupContent = html; return this; };
  Marker.prototype.openPopup = function () {
    if (this._popupContent == null || !this._map) return this;
    if (!this._popupEl) {
      this._popupEl = el('div',
        'position:absolute;transform:translate(-50%,calc(-100% - 18px));' +
        'background:#fff;border-radius:8px;padding:8px 10px;font:12px/1.4 sans-serif;' +
        'box-shadow:0 4px 14px rgba(0,0,0,.25);white-space:nowrap;pointer-events:auto;',
        this._map._popupPane);
    }
    this._popupEl.innerHTML = this._popupContent;
    this._popupEl.style.display = 'block';
    this._popupOpen = true; this._map._schedule(); return this;
  };
  Marker.prototype.closePopup = function () {
    if (this._popupEl) this._popupEl.style.display = 'none';
    this._popupOpen = false; return this;
  };
  Marker.prototype.togglePopup = function () {
    return this._popupOpen ? this.closePopup() : this.openPopup();
  };
  Marker.prototype.remove = function () {
    if (!this._map) return this;
    this._map._markerPane.removeChild(this._outer);
    if (this._popupEl) this._map._popupPane.removeChild(this._popupEl);
    this._map._markers = this._map._markers.filter(function (m) { return m !== this; }, this);
    var arr = this._map._markers, i = arr.indexOf(this);
    if (i >= 0) arr.splice(i, 1);
    this._map = null; return this;
  };

  // =====================================================================
  //  POLYLINE
  // =====================================================================
  function Polyline(latlngs, opts) {
    opts = opts || {};
    this._pts = (latlngs || []).map(LL);
    this.color = opts.color || '#EF4444';
    this.weight = opts.weight || 4;
    this.opacity = opts.opacity != null ? opts.opacity : 1;
    this.dash = opts.dashArray || null;
  }
  Polyline.prototype.addTo = function (map) {
    this._map = map;
    this._node = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    this._node.setAttribute('fill', 'none');
    this._node.setAttribute('stroke', this.color);
    this._node.setAttribute('stroke-width', this.weight);
    this._node.setAttribute('stroke-opacity', this.opacity);
    this._node.setAttribute('stroke-linejoin', 'round');
    this._node.setAttribute('stroke-linecap', 'round');
    if (this.dash) this._node.setAttribute('stroke-dasharray', this.dash);
    map._svg.appendChild(this._node);
    map._vectors.push(this); map._schedule(); return this;
  };
  Polyline.prototype._draw = function (map, OFF) {
    var z = map._zoom, wc = map._wc, pts = '';
    for (var i = 0; i < this._pts.length; i++) {
      var w = project(this._pts[i].lat, this._pts[i].lng, z);
      pts += (w.x - wc.x + OFF) + ',' + (w.y - wc.y + OFF) + ' ';
    }
    this._node.setAttribute('points', pts.trim());
  };
  Polyline.prototype.setLatLngs = function (arr) {
    this._pts = (arr || []).map(LL); if (this._map) this._map._schedule(); return this;
  };
  Polyline.prototype.getLatLngs = function () {
    return this._pts.map(function (p) { return { lat: p.lat, lng: p.lng }; });
  };
  Polyline.prototype.addLatLng = function (latlng) {
    this._pts.push(LL(latlng)); if (this._map) this._map._schedule(); return this;
  };

  // =====================================================================
  //  CIRCLE  (radius in METERS — like Leaflet)
  // =====================================================================
  function Circle(latlng, opts) {
    opts = opts || {};
    this._ll = LL(latlng);
    this.radius = opts.radius || 10;
    this.color = opts.color || '#3B82F6';
    this.weight = opts.weight != null ? opts.weight : 2;
    this.fill = opts.fillColor || '#93C5FD';
    this.fillOpacity = opts.fillOpacity != null ? opts.fillOpacity : 0.15;
    this.dash = opts.dashArray || null;
    this.minRadiusPx = opts.minRadiusPx || 0;
  }
  Circle.prototype.addTo = function (map) {
    this._map = map;
    this._node = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    this._node.setAttribute('stroke', this.color);
    this._node.setAttribute('stroke-width', this.weight);
    this._node.setAttribute('fill', this.fill);
    this._node.setAttribute('fill-opacity', this.fillOpacity);
    if (this.dash) this._node.setAttribute('stroke-dasharray', this.dash);
    map._svg.appendChild(this._node);
    map._vectors.push(this); map._schedule(); return this;
  };
  Circle.prototype._draw = function (map, OFF) {
    var w = project(this._ll.lat, this._ll.lng, map._zoom);
    var mpp = metersPerPixel(this._ll.lat, map._zoom);
    this._node.setAttribute('cx', w.x - map._wc.x + OFF);
    this._node.setAttribute('cy', w.y - map._wc.y + OFF);
    this._node.setAttribute('r', Math.max(this.radius / mpp, this.minRadiusPx));
  };
  Circle.prototype.setLatLng = function (latlng) {
    this._ll = LL(latlng); if (this._map) this._map._schedule(); return this;
  };
  Circle.prototype.setRadius = function (m) {
    this.radius = m; if (this._map) this._map._schedule(); return this;
  };

  // =====================================================================
  //  RECTANGLE  (width/height in METERS, optional heading rotation)
  //  Great for obstacles/zones with a real footprint and orientation.
  // =====================================================================
  function Rectangle(latlng, opts) {
    opts = opts || {};
    this._ll = LL(latlng);
    this.width = opts.width || 1;       // meters along the "right" axis (east at rotation 0)
    this.height = opts.height || 1;     // meters along the "up" axis (north at rotation 0)
    this.rotation = opts.rotation || 0; // heading of the up-axis, deg clockwise from North
    this.color = opts.color || '#F97316';
    this.weight = opts.weight != null ? opts.weight : 2;
    this.fill = opts.fillColor || opts.color || '#F97316';
    this.fillOpacity = opts.fillOpacity != null ? opts.fillOpacity : 0.25;
    this.dash = opts.dashArray || null;
  }
  Rectangle.prototype.addTo = function (map) {
    this._map = map;
    this._node = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    this._node.setAttribute('stroke', this.color);
    this._node.setAttribute('stroke-width', this.weight);
    this._node.setAttribute('fill', this.fill);
    this._node.setAttribute('fill-opacity', this.fillOpacity);
    this._node.setAttribute('stroke-linejoin', 'round');
    if (this.dash) this._node.setAttribute('stroke-dasharray', this.dash);
    map._svg.appendChild(this._node);
    map._vectors.push(this); map._schedule(); return this;
  };
  Rectangle.prototype._draw = function (map, OFF) {
    var w = project(this._ll.lat, this._ll.lng, map._zoom);
    var mpp = metersPerPixel(this._ll.lat, map._zoom);
    var hw = (this.width / 2) / mpp, hh = (this.height / 2) / mpp;
    var r = this.rotation * DEG;
    // world-px unit axes (y is +south): up(height) along heading r, right(width) along r+90
    var ux = Math.sin(r), uy = -Math.cos(r);
    var rx = Math.cos(r), ry = Math.sin(r);
    var cx = w.x - map._wc.x + OFF, cy = w.y - map._wc.y + OFF;
    var c = [
      [cx - rx * hw + ux * hh, cy - ry * hw + uy * hh],
      [cx + rx * hw + ux * hh, cy + ry * hw + uy * hh],
      [cx + rx * hw - ux * hh, cy + ry * hw - uy * hh],
      [cx - rx * hw - ux * hh, cy - ry * hw - uy * hh]
    ];
    this._node.setAttribute('points', c.map(function (p) { return p[0] + ',' + p[1]; }).join(' '));
  };
  Rectangle.prototype.setLatLng = function (ll) { this._ll = LL(ll); if (this._map) this._map._schedule(); return this; };
  Rectangle.prototype.setRotation = function (d) { this.rotation = d; if (this._map) this._map._schedule(); return this; };
  Rectangle.prototype.setSize = function (wm, hm) { this.width = wm; this.height = hm; if (this._map) this._map._schedule(); return this; };

  // =====================================================================
  //  POLYGON  (arbitrary obstacle shape, geographic coordinates)
  // =====================================================================
  function Polygon(latlngs, opts) {
    opts = opts || {};
    this._pts = (latlngs || []).map(LL);
    this.color = opts.color || '#F97316';
    this.weight = opts.weight != null ? opts.weight : 2;
    this.fill = opts.fillColor || opts.color || '#F97316';
    this.fillOpacity = opts.fillOpacity != null ? opts.fillOpacity : 0.25;
    this.dash = opts.dashArray || null;
  }
  Polygon.prototype.addTo = function (map) {
    this._map = map;
    this._node = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    this._node.setAttribute('stroke', this.color);
    this._node.setAttribute('stroke-width', this.weight);
    this._node.setAttribute('fill', this.fill);
    this._node.setAttribute('fill-opacity', this.fillOpacity);
    this._node.setAttribute('stroke-linejoin', 'round');
    if (this.dash) this._node.setAttribute('stroke-dasharray', this.dash);
    map._svg.appendChild(this._node);
    map._vectors.push(this); map._schedule(); return this;
  };
  Polygon.prototype._draw = function (map, OFF) {
    var z = map._zoom, wc = map._wc, pts = '';
    for (var i = 0; i < this._pts.length; i++) {
      var w = project(this._pts[i].lat, this._pts[i].lng, z);
      pts += (w.x - wc.x + OFF) + ',' + (w.y - wc.y + OFF) + ' ';
    }
    this._node.setAttribute('points', pts.trim());
  };
  Polygon.prototype.setLatLngs = function (a) { this._pts = (a || []).map(LL); if (this._map) this._map._schedule(); return this; };
  Polygon.prototype.getLatLngs = function () { return this._pts.map(function (p) { return { lat: p.lat, lng: p.lng }; }); };

  // =====================================================================
  //  FACTORY (Leaflet-style: RotaMap.map(), RotaMap.marker(), ...)
  // =====================================================================
  var RotaMap = {
    map: function (c, o) { return new RMap(c, o); },
    tileLayer: function (u, o) { return new TileLayer(u, o); },
    marker: function (ll, o) { return new Marker(ll, o); },
    polyline: function (a, o) { return new Polyline(a, o); },
    circle: function (ll, o) { return new Circle(ll, o); },
    rectangle: function (ll, o) { return new Rectangle(ll, o); },
    polygon: function (a, o) { return new Polygon(a, o); },
    divIcon: function (o) { return new DivIcon(o); },
    project: project,
    unproject: unproject,
    metersPerPixel: metersPerPixel,
    Map: RMap, TileLayer: TileLayer, Marker: Marker,
    Polyline: Polyline, Circle: Circle, Rectangle: Rectangle,
    Polygon: Polygon, DivIcon: DivIcon
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = RotaMap;
  global.RotaMap = RotaMap;
})(typeof window !== 'undefined' ? window : this);