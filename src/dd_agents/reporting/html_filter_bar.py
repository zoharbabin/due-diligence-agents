"""Client-side filter bar — severity + domain chip filtering (Issue #196).

Renders a sticky filter bar with chip buttons for severities and domains.
Toggles visibility of `[data-severity]` and `[data-domain]` elements via JS.
URL hash state enables shareable filtered views.

Progressive enhancement: all content visible without JS. Filter bar is
cosmetic enhancement only — report remains fully usable with JS disabled.
"""

from __future__ import annotations

from dd_agents.reporting.html_base import (
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SEVERITY_COLORS,
    SectionRenderer,
    get_domain_agents,
)
from dd_agents.utils.constants import ALL_SEVERITIES


class FilterBarRenderer(SectionRenderer):
    """Render a sticky filter bar with severity and domain chip buttons."""

    def render(self) -> str:
        parts: list[str] = [
            "<div class='filter-bar' role='toolbar' aria-label='Finding filters'>",
            "<div class='filter-bar-group'>",
            "<span class='filter-bar-label'>Severity:</span>",
        ]

        for sev in ALL_SEVERITIES:
            color = SEVERITY_COLORS[sev]
            parts.append(
                f"<button class='filter-chip filter-chip--severity' "
                f"data-filter-severity='{self.escape(sev)}' "
                f"style='--chip-color:{color}' "
                f"aria-pressed='false' "
                f"type='button'>{self.escape(sev)}</button>"
            )

        parts.append("</div><div class='filter-bar-group'>")
        parts.append("<span class='filter-bar-label'>Domain:</span>")

        for domain in get_domain_agents():
            display = DOMAIN_DISPLAY.get(domain, domain.capitalize())
            color = DOMAIN_COLORS.get(domain, "#333")
            parts.append(
                f"<button class='filter-chip filter-chip--domain' "
                f"data-filter-domain='{self.escape(domain)}' "
                f"style='--chip-color:{color}' "
                f"aria-pressed='false' "
                f"type='button'>{self.escape(display)}</button>"
            )

        parts.append("</div>")

        # Free-text search (Issue #191) — matches title + description + citations.
        parts.append("<div class='filter-bar-group'>")
        parts.append("<span class='filter-bar-label'>Search:</span>")
        parts.append(
            "<input type='search' class='filter-search' placeholder='Search findings…' aria-label='Search findings'>"
        )
        parts.append("</div>")

        # Entity dropdown (Issue #191) — filters finding cards by entity.
        entity_options = "".join(
            f"<option value='{self.escape(csn)}'>{self.escape(name)}</option>"
            for csn, name in sorted(self.data.display_names.items(), key=lambda kv: kv[1].lower())
        )
        parts.append("<div class='filter-bar-group'>")
        parts.append("<span class='filter-bar-label'>Entity:</span>")
        parts.append(
            "<select class='filter-entity' aria-label='Filter by entity'>"
            "<option value=''>All entities</option>"
            f"{entity_options}</select>"
        )
        parts.append("</div>")

        parts.append(
            "<div class='filter-bar-status'>"
            "<span class='filter-count' aria-live='polite' aria-atomic='true'></span>"
            "<button class='filter-clear hidden' type='button' aria-label='Clear all filters'>Clear</button>"
            "</div>"
        )
        parts.append("</div>")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS for the filter bar (appended to main CSS)
# ---------------------------------------------------------------------------

FILTER_BAR_CSS = """
/* Filter Bar (Issue #196) */
.filter-bar { position: sticky; top: 0; z-index: 500; background: var(--bg-secondary);
              border-bottom: 1px solid var(--border-light); padding: 10px 16px;
              display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
              box-shadow: var(--shadow-sm); }
.filter-bar-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.filter-bar-label { font-size: 0.78em; font-weight: 600; color: var(--text-secondary);
                    text-transform: uppercase; letter-spacing: 0.5px; }
.filter-chip { border: 1.5px solid var(--chip-color, #ccc); background: transparent;
               color: var(--chip-color, #333); border-radius: 16px; padding: 3px 12px;
               font-size: 0.8em; font-weight: 600; cursor: pointer;
               transition: background 0.15s, color 0.15s; }
.filter-chip:hover { background: rgba(0,0,0,0.06); }
@supports (background: color-mix(in srgb, red 50%, blue)) {
  .filter-chip:hover { background: color-mix(in srgb, var(--chip-color) 15%, transparent); }
}
.filter-chip[aria-pressed='true'] { background: var(--chip-color); color: #fff; }
.filter-search { border: 1px solid var(--border-light); border-radius: 16px;
                 padding: 3px 12px; font-size: 0.8em; min-width: 160px; color: var(--text-primary);
                 background: var(--bg-primary); }
.filter-entity { border: 1px solid var(--border-light); border-radius: 16px;
                 padding: 3px 8px; font-size: 0.8em; color: var(--text-primary);
                 background: var(--bg-primary); }
.filter-bar-status { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.filter-count { font-size: 0.8em; color: var(--text-secondary); }
.filter-clear { border: none; background: none; color: var(--blue); font-size: 0.8em;
                cursor: pointer; text-decoration: underline; padding: 2px 6px; }
.filter-clear:hover { color: var(--red); }
.filter-results-banner { background: #fff3cd; border-bottom: 1px solid #ffc107;
                         padding: 8px 16px; font-size: 0.85em; color: #664d03; }
.filter-results-banner a { color: #0d6efd; font-weight: 600; }
@media print { .filter-bar, .filter-results-banner { display: none !important; } }
@media (max-width: 900px) { .filter-bar { position: static; } }
"""

# ---------------------------------------------------------------------------
# JS for the filter bar (appended to main JS)
# ---------------------------------------------------------------------------

FILTER_BAR_JS = r"""
// --- Filter Bar (Issue #196) ---
(function() {
    'use strict';
    var bar = document.querySelector('.filter-bar');
    if (!bar) return;

    var activeSev = new Set();
    var activeDom = new Set();
    var activeEntity = '';
    var searchText = '';
    var countEl = bar.querySelector('.filter-count');
    var clearBtn = bar.querySelector('.filter-clear');
    var searchInput = bar.querySelector('.filter-search');
    var entitySelect = bar.querySelector('.filter-entity');
    var allFilterable = document.querySelectorAll('[data-severity]');
    // Also tag table rows containing severity badges for filtering
    document.querySelectorAll('tr:not([data-severity])').forEach(function(tr) {
        var badge = tr.querySelector('.severity-badge');
        if (!badge) return;
        var text = badge.textContent.trim();
        var match = text.match(/P[0-3]/);
        if (match) {
            tr.setAttribute('data-severity', match[0]);
            // Try to infer domain from section context
            var sec = tr.closest('section[id]');
            if (sec) {
                var secId = sec.id;
                var domMatch = secId.match(/sec-domain-(\w+)/);
                if (domMatch) tr.setAttribute('data-domain', domMatch[1]);
            }
        }
    });
    allFilterable = document.querySelectorAll('[data-severity]');
    var totalCount = allFilterable.length;

    // Create results banner (shows below filter bar when active)
    var banner = document.createElement('div');
    banner.className = 'filter-results-banner';
    banner.style.display = 'none';
    bar.parentNode.insertBefore(banner, bar.nextSibling);

    function applyFilters() {
        if (totalCount === 0) return;
        var noFilter = activeSev.size === 0 && activeDom.size === 0
            && activeEntity === '' && searchText === '';
        var visibleCount = 0;
        var firstVisible = null;
        allFilterable.forEach(function(el) {
            var sev = el.getAttribute('data-severity');
            var dom = el.getAttribute('data-domain');
            var sevMatch = activeSev.size === 0 || activeSev.has(sev);
            var domMatch = activeDom.size === 0 || activeDom.has(dom);
            var entMatch = activeEntity === '' || el.getAttribute('data-entity') === activeEntity;
            var txtMatch = true;
            // Adjacent .finding-detail sibling carries description + citations.
            var detail = el.nextElementSibling;
            var hasDetail = detail && detail.classList.contains('finding-detail');
            if (searchText !== '') {
                var hay = el.textContent;
                if (hasDetail) hay += ' ' + detail.textContent;
                txtMatch = hay.toLowerCase().indexOf(searchText) !== -1;
            }
            var visible = sevMatch && domMatch && entMatch && txtMatch;
            el.style.display = visible ? '' : 'none';
            // Keep the detail's visibility consistent with its card. When visible,
            // clear inline display so the .open class controls expand state again.
            if (hasDetail) detail.style.display = visible ? '' : 'none';
            if (visible) {
                visibleCount++;
                if (!firstVisible) firstVisible = el;
            }
        });
        // Hide parent containers (categories, domains, sections) when all children hidden
        document.querySelectorAll('.category-body, .domain-body, .subject-body').forEach(function(body) {
            var children = body.querySelectorAll('[data-severity]');
            if (children.length === 0) return;
            var anyVisible = noFilter || Array.from(children).some(function(c) { return c.style.display !== 'none'; });
            var wrapper = body.parentElement;
            if (wrapper) wrapper.style.display = anyVisible ? '' : 'none';
        });
        // Hide report sections that have only filtered-out content
        document.querySelectorAll('section.report-section').forEach(function(sec) {
            var children = sec.querySelectorAll('[data-severity]');
            if (children.length === 0) return;
            var anyVisible = noFilter || Array.from(children).some(function(c) { return c.style.display !== 'none'; });
            sec.style.display = anyVisible ? '' : 'none';
        });
        if (noFilter) {
            countEl.textContent = '';
            clearBtn.classList.add('hidden');
            banner.style.display = 'none';
        } else {
            countEl.textContent = visibleCount + ' of ' + totalCount + ' findings shown';
            clearBtn.classList.remove('hidden');
            // Show results banner with safe DOM construction (no innerHTML)
            var labels = [];
            activeSev.forEach(function(s) { labels.push(s); });
            activeDom.forEach(function(d) { labels.push(d.charAt(0).toUpperCase() + d.slice(1)); });
            banner.textContent = '';
            var strong = document.createElement('strong');
            strong.textContent = 'Showing ' + visibleCount + ' of ' + totalCount;
            banner.appendChild(strong);
            banner.appendChild(document.createTextNode(' findings matching: ' + labels.join(', ') + ' — '));
            var jumpLink = document.createElement('a');
            jumpLink.href = '#';
            jumpLink.className = 'filter-jump';
            jumpLink.textContent = 'Jump to first result';
            jumpLink.onclick = function(e) {
                e.preventDefault();
                if (firstVisible) firstVisible.scrollIntoView({behavior:'smooth', block:'center'});
            };
            banner.appendChild(jumpLink);
            banner.style.display = '';
        }
        syncHash();
    }

    function syncHash() {
        try {
            var parts = [];
            if (activeSev.size > 0) parts.push('sev=' + Array.from(activeSev).join(','));
            if (activeDom.size > 0) parts.push('dom=' + Array.from(activeDom).join(','));
            if (activeEntity) parts.push('ent=' + encodeURIComponent(activeEntity));
            if (searchText) parts.push('q=' + encodeURIComponent(searchText));
            if (parts.length > 0) {
                history.replaceState(null, '', '#filter:' + parts.join('&'));
            } else {
                history.replaceState(null, '', window.location.pathname + window.location.search);
            }
        } catch(e) {}
    }

    // Build allowlists from rendered chip buttons (known-safe values only)
    var knownSev = new Set();
    var knownDom = new Set();
    var knownEnt = new Set();
    bar.querySelectorAll('.filter-chip--severity').forEach(function(btn) {
        knownSev.add(btn.getAttribute('data-filter-severity'));
    });
    bar.querySelectorAll('.filter-chip--domain').forEach(function(btn) {
        knownDom.add(btn.getAttribute('data-filter-domain'));
    });
    if (entitySelect) {
        Array.from(entitySelect.options).forEach(function(opt) {
            if (opt.value) knownEnt.add(opt.value);
        });
    }

    function readHash() {
        var hash = window.location.hash.slice(1);
        if (!hash || !hash.startsWith('filter:')) return;
        hash = hash.slice(7);
        hash.split('&').forEach(function(part) {
            var kv = part.split('=');
            if (kv.length !== 2) return;
            var key = kv[0], vals = kv[1].split(',');
            if (key === 'sev') vals.forEach(function(v) { if (knownSev.has(v)) activeSev.add(v); });
            if (key === 'dom') vals.forEach(function(v) { if (knownDom.has(v)) activeDom.add(v); });
            if (key === 'ent') {
                var ent = decodeURIComponent(kv[1]);
                if (knownEnt.has(ent)) { activeEntity = ent; if (entitySelect) entitySelect.value = ent; }
            }
            if (key === 'q') {
                searchText = decodeURIComponent(kv[1]).toLowerCase();
                if (searchInput) searchInput.value = decodeURIComponent(kv[1]);
            }
        });
        bar.querySelectorAll('.filter-chip--severity').forEach(function(btn) {
            if (activeSev.has(btn.getAttribute('data-filter-severity'))) {
                btn.setAttribute('aria-pressed', 'true');
            }
        });
        bar.querySelectorAll('.filter-chip--domain').forEach(function(btn) {
            if (activeDom.has(btn.getAttribute('data-filter-domain'))) {
                btn.setAttribute('aria-pressed', 'true');
            }
        });
        applyFilters();
    }

    bar.querySelectorAll('.filter-chip--severity').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var sev = this.getAttribute('data-filter-severity');
            if (activeSev.has(sev)) { activeSev.delete(sev); this.setAttribute('aria-pressed', 'false'); }
            else { activeSev.add(sev); this.setAttribute('aria-pressed', 'true'); }
            applyFilters();
        });
    });

    bar.querySelectorAll('.filter-chip--domain').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var dom = this.getAttribute('data-filter-domain');
            if (activeDom.has(dom)) { activeDom.delete(dom); this.setAttribute('aria-pressed', 'false'); }
            else { activeDom.add(dom); this.setAttribute('aria-pressed', 'true'); }
            applyFilters();
        });
    });

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            searchText = this.value.trim().toLowerCase();
            applyFilters();
        });
    }

    if (entitySelect) {
        entitySelect.addEventListener('change', function() {
            activeEntity = this.value;
            applyFilters();
        });
    }

    clearBtn.addEventListener('click', function() {
        activeSev.clear();
        activeDom.clear();
        activeEntity = '';
        searchText = '';
        if (searchInput) searchInput.value = '';
        if (entitySelect) entitySelect.value = '';
        bar.querySelectorAll('.filter-chip').forEach(function(btn) {
            btn.setAttribute('aria-pressed', 'false');
        });
        applyFilters();
    });

    readHash();
})();
"""
