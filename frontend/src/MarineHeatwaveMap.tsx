import { useMemo, useRef, useState, type PointerEvent } from 'react';
import './marine-heatwave-map.css';

type MhwEvent = {
  start: string;
  end: string;
  duration_days: number;
  exceedance_days?: number;
  mean_intensity_c: number;
  maximum_intensity_c: number;
  cumulative_intensity_c_days?: number;
};
type MhwCell = { latitude: number; longitude: number; area_km2?: number; events: MhwEvent[] };
type DailyCoverage = {
  date: string;
  valid_cells: number;
  affected_cells: number;
  percent_area_affected: number;
  affected_area_km2: number;
};
type MhwAnalysis = {
  status: string;
  reason?: string;
  region?: string;
  dataset?: string;
  dataset_id?: string;
  baseline_dataset_id?: string;
  target_period?: { start: string; end: string } | string[];
  baseline_period?: string[];
  verification_status?: string;
  grid_spacing_degrees?: { latitude: number; longitude: number };
  valid_cells?: number;
  affected_cells?: number;
  area_weighted_percent_affected_any_day?: number;
  target_missing_fraction?: number;
  target_total_values?: number;
  target_valid_values?: number;
  target_url?: string;
  baseline_url?: string;
  baseline_quality?: { missing_fraction?: number; annual_chunks?: number };
  event_cells?: MhwCell[];
  hotspots?: MhwCell[];
  daily_spatial_coverage?: DailyCoverage[];
  provenance?: Array<{ source?: string; url?: string; period?: string[]; dataset_id?: string }>;
  method?: string;
  limitations?: string[];
};
type Bounds = { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
type Layer = 'classification' | 'mean' | 'peak' | 'hotspots';
type Point = { x: number; y: number };

const MAP_WIDTH = 960;
const MAP_HEIGHT = 600;
const MIN_ZOOM = 3;
const MAX_ZOOM = 8;
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const cellKey = (cell: Pick<MhwCell, 'latitude' | 'longitude'>) => `${cell.latitude.toFixed(3)},${cell.longitude.toFixed(3)}`;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const coordinate = (value: number, axis: 'lat' | 'lon') => `${Math.abs(value).toFixed(3)}°${axis === 'lat' ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E')}`;

function project(longitude: number, latitude: number, zoom: number): Point {
  const world = 256 * 2 ** zoom;
  const lat = clamp(latitude, -85.05112878, 85.05112878) * Math.PI / 180;
  return { x: (longitude + 180) / 360 * world,
    y: (1 - Math.log(Math.tan(lat) + 1 / Math.cos(lat)) / Math.PI) / 2 * world };
}

function targetPeriod(value: MhwAnalysis['target_period']) {
  if (Array.isArray(value)) return value.length > 1 ? `${value[0]} to ${value[1]}` : value[0] || 'Unavailable';
  if (value && typeof value === 'object') return `${value.start} to ${value.end}`;
  return 'Unavailable';
}

function colorFor(value: number, max: number) {
  const ratio = clamp(value / Math.max(max, 0.01), 0, 1);
  const low = [73, 190, 177], high = [244, 171, 88];
  const rgb = low.map((channel, index) => Math.round(channel + (high[index] - channel) * ratio));
  return `rgb(${rgb.join(',')})`;
}

function initialMap(bounds?: Bounds) {
  if (!bounds || ![bounds.lat_min, bounds.lat_max, bounds.lon_min, bounds.lon_max].every(finite)) {
    return { center: { lat: 17.5, lon: 65 }, zoom: 5 };
  }
  return { center: { lat: (bounds.lat_min + bounds.lat_max) / 2,
    lon: (bounds.lon_min + bounds.lon_max) / 2 }, zoom: 5 };
}

export default function MarineHeatwaveMap({ analysis, bounds }: { analysis: MhwAnalysis; bounds?: Bounds }) {
  const initial = useMemo(() => initialMap(bounds), [bounds]);
  const [layer, setLayer] = useState<Layer>('classification');
  const [dayIndex, setDayIndex] = useState(0);
  const [zoom, setZoom] = useState(initial.zoom);
  const [center, setCenter] = useState(initial.center);
  const [selected, setSelected] = useState<MhwCell | null>(null);
  const [basemapUnavailable, setBasemapUnavailable] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ pointerId: number; x: number; y: number; center: Point } | null>(null);

  const events = (Array.isArray(analysis.event_cells) ? analysis.event_cells : [])
    .filter(cell => finite(cell.latitude) && finite(cell.longitude) && cell.latitude >= -85 && cell.latitude <= 85 &&
      cell.longitude >= -180 && cell.longitude <= 180 && Array.isArray(cell.events))
    .map(cell => ({ ...cell, events: cell.events.filter(event => typeof event.start === 'string' &&
      typeof event.end === 'string' && finite(event.duration_days) && finite(event.mean_intensity_c) &&
      finite(event.maximum_intensity_c)) }))
    .filter(cell => cell.events.length > 0);
  const daily = (Array.isArray(analysis.daily_spatial_coverage) ? analysis.daily_spatial_coverage : []).filter(item =>
    typeof item.date === 'string' && finite(item.valid_cells) && finite(item.affected_cells) &&
    finite(item.percent_area_affected) && finite(item.affected_area_km2));
  const safeDayIndex = clamp(dayIndex, 0, Math.max(daily.length - 1, 0));
  const selectedDay = daily[safeDayIndex];
  const date = selectedDay?.date;
  const isActive = (event: MhwEvent) => !date || (event.start <= date && event.end >= date);
  const activeCells = events.filter(cell => cell.events.some(isActive));
  const activeKeys = new Set(activeCells.map(cellKey));
  const hotspotKeys = new Set((analysis.hotspots || []).filter(cell => activeKeys.has(cellKey(cell))).map(cellKey));
  const anomalyValues = events.flatMap(cell => cell.events.map(event => event.mean_intensity_c).filter(finite));
  const peakValues = events.flatMap(cell => cell.events.map(event => event.maximum_intensity_c).filter(finite));
  const meanMax = Math.max(...anomalyValues, 0.01);
  const peakMax = Math.max(...peakValues, 0.01);
  const longestEvent = events.flatMap(cell => cell.events).reduce<MhwEvent | null>((longest, event) =>
    !longest || event.duration_days > longest.duration_days ? event : longest, null);
  const spacingLat = analysis.grid_spacing_degrees?.latitude || 0.25;
  const spacingLon = analysis.grid_spacing_degrees?.longitude || 0.25;
  const centerPixel = project(center.lon, center.lat, zoom);
  const view = { x: centerPixel.x - MAP_WIDTH / 2, y: centerPixel.y - MAP_HEIGHT / 2 };
  const firstTileX = Math.floor(view.x / 256);
  const lastTileX = Math.floor((view.x + MAP_WIDTH) / 256);
  const firstTileY = Math.floor(view.y / 256);
  const lastTileY = Math.floor((view.y + MAP_HEIGHT) / 256);
  const tileCount = 2 ** zoom;
  const tiles: Array<{ key: string; x: number; y: number; url: string }> = [];
  for (let y = firstTileY; y <= lastTileY; y += 1) {
    if (y < 0 || y >= tileCount) continue;
    for (let x = firstTileX; x <= lastTileX; x += 1) {
      const wrappedX = ((x % tileCount) + tileCount) % tileCount;
      tiles.push({ key: `${zoom}/${x}/${y}`, x: x * 256, y: y * 256,
        url: TILE_URL.replace('{z}', String(zoom)).replace('{x}', String(wrappedX)).replace('{y}', String(y)) });
    }
  }

  function cellColor(cell: MhwCell) {
    const relevant = cell.events.filter(isActive);
    if (layer === 'hotspots') return hotspotKeys.has(cellKey(cell)) ? '#ffd078' : '#496f75';
    if (layer === 'mean') return colorFor(Math.max(...relevant.map(event => event.mean_intensity_c), 0), meanMax);
    if (layer === 'peak') return colorFor(Math.max(...relevant.map(event => event.maximum_intensity_c), 0), peakMax);
    return '#5bd5c7';
  }

  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if ((event.target as Element).closest('[data-cell]')) return;
    const point = project(center.lon, center.lat, zoom);
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, center: point };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function pointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const dx = (event.clientX - drag.current.x) * MAP_WIDTH / rect.width;
    const dy = (event.clientY - drag.current.y) * MAP_HEIGHT / rect.height;
    const world = 256 * 2 ** zoom;
    const x = ((drag.current.center.x - dx) % world + world) % world;
    const y = clamp(drag.current.center.y - dy, 0, world);
    const lon = x / world * 360 - 180;
    const mercator = Math.PI * (1 - 2 * y / world);
    const lat = Math.atan(Math.sinh(mercator)) * 180 / Math.PI;
    setCenter({ lon, lat });
  }
  function pointerUp(event: PointerEvent<SVGSVGElement>) {
    if (drag.current?.pointerId === event.pointerId) drag.current = null;
  }
  function zoomBy(delta: number) {
    setZoom(old => clamp(old + delta, MIN_ZOOM, MAX_ZOOM));
  }

  const peakArea = finite(analysis.area_weighted_percent_affected_any_day)
    ? analysis.area_weighted_percent_affected_any_day : null;
  const peakAnomaly = peakValues.length ? Math.max(...peakValues) : null;
  const resultAvailable = ['mhw_detected', 'no_mhw_detected'].includes(analysis.status) &&
    finite(analysis.valid_cells) && !!analysis.grid_spacing_degrees;
  const targetProvenance = analysis.provenance?.find(item => item.period?.length === 2 && item.dataset_id);
  const baselineProvenance = analysis.provenance?.find(item => item.source?.toLowerCase().includes('final'));

  return <section className="panel mhw-map-panel" aria-label="Spatial marine heatwave analysis">
    <div className="mhw-map-heading">
      <div><span className="overline">SPATIAL EVENT FOOTPRINT · NATIVE GRID</span>
        <h2>{analysis.region || 'Marine heatwave'} spatial analysis</h2>
        <p>{analysis.method || 'Grid-cell marine heatwave event detection'} · {analysis.grid_spacing_degrees?.latitude ?? '—'}° × {analysis.grid_spacing_degrees?.longitude ?? '—'}° cells</p>
      </div>
      <span className={`mhw-status ${resultAvailable ? 'verified' : 'unavailable'}`}>{resultAvailable ? 'DETECTOR OUTPUT' : 'SPATIAL RESULT UNAVAILABLE'}</span>
    </div>

    {!resultAvailable ? <div className="mhw-map-empty" role="status">
      <strong>Spatial event map unavailable for this run</strong>
      <p>{analysis.reason || 'The detector did not return validated grid metadata. No event map is shown.'}</p>
    </div> : <>
      <div className="mhw-summary-strip">
        <div><small>ANALYSIS PERIOD</small><b>{targetPeriod(analysis.target_period)}</b></div>
        <div><small>BASELINE</small><b>{analysis.baseline_period?.join('–') || 'Unavailable'}</b></div>
        <div><small>VALID OCEAN CELLS</small><b>{analysis.valid_cells?.toLocaleString()}</b></div>
        <div><small>CELLS WITH EVENTS</small><b>{analysis.affected_cells?.toLocaleString() ?? events.length.toLocaleString()}</b></div>
        <div><small>MAX AREA AFFECTED</small><b>{peakArea === null ? '—' : `${peakArea.toFixed(1)}%`}</b></div>
        <div><small>PEAK EVENT INTENSITY</small><b>{peakAnomaly === null ? '—' : `${peakAnomaly.toFixed(2)}°C`}</b></div>
        <div><small>LONGEST CELL EVENT</small><b>{longestEvent ? `${longestEvent.duration_days} days` : '—'}</b></div>
      </div>

      <div className="mhw-map-toolbar">
        <div className="mhw-layer-control" role="group" aria-label="Map display layer">
          {([['classification', 'MHW cells'], ['mean', 'Mean event anomaly'], ['peak', 'Peak intensity'], ['hotspots', 'Hotspots']] as const).map(([id, label]) =>
            <button key={id} type="button" className={layer === id ? 'active' : ''} onClick={() => setLayer(id)}>{label}</button>)}
        </div>
        <div className="mhw-zoom-control" aria-label="Map zoom controls">
          <button type="button" onClick={() => zoomBy(1)} aria-label="Zoom in" disabled={zoom >= MAX_ZOOM}>+</button>
          <span>z{zoom}</span>
          <button type="button" onClick={() => zoomBy(-1)} aria-label="Zoom out" disabled={zoom <= MIN_ZOOM}>−</button>
          <button type="button" onClick={() => { setCenter({ lat: initial.center.lat, lon: initial.center.lon }); setZoom(initial.zoom); }} aria-label="Reset map">Reset</button>
        </div>
      </div>

      <div className="mhw-map-layout">
        <div className="mhw-map-wrap">
          {analysis.status === 'no_mhw_detected' && <div className="mhw-no-events">No qualifying grid-cell events detected in this analysis period.</div>}
          <svg ref={svgRef} className="mhw-map-svg" viewBox={`${view.x} ${view.y} ${MAP_WIDTH} ${MAP_HEIGHT}`} role="img"
            aria-label={`Map of ${activeCells.length.toLocaleString()} marine heatwave cells on ${date || 'the analysis period'}`}
            onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
            <rect x={view.x} y={view.y} width={MAP_WIDTH} height={MAP_HEIGHT} fill="#0b2429" />
            {tiles.map(tile => <image key={tile.key} href={tile.url} x={tile.x} y={tile.y} width="256" height="256" className="mhw-map-tile"
              onLoad={() => setBasemapUnavailable(false)} onError={() => setBasemapUnavailable(true)} />)}
            {bounds && [bounds.lat_min, bounds.lat_max, bounds.lon_min, bounds.lon_max].every(finite) && (() => {
              const nw = project(bounds.lon_min, bounds.lat_max, zoom);
              const se = project(bounds.lon_max, bounds.lat_min, zoom);
              return <rect x={nw.x} y={nw.y} width={se.x - nw.x} height={se.y - nw.y} className="mhw-region-boundary" />;
            })()}
            {activeCells.map(cell => {
              const nw = project(cell.longitude - spacingLon / 2, cell.latitude + spacingLat / 2, zoom);
              const se = project(cell.longitude + spacingLon / 2, cell.latitude - spacingLat / 2, zoom);
              const eventsForDay = cell.events.filter(isActive);
              const title = `${coordinate(cell.latitude, 'lat')}, ${coordinate(cell.longitude, 'lon')} · ${eventsForDay.map(event => `${event.duration_days} days; mean anomaly ${event.mean_intensity_c.toFixed(2)}°C; peak ${event.maximum_intensity_c.toFixed(2)}°C`).join('; ')}`;
              return <rect key={cellKey(cell)} data-cell="true" x={nw.x} y={nw.y} width={Math.max(se.x - nw.x, 1)} height={Math.max(se.y - nw.y, 1)}
                fill={cellColor(cell)} className={`mhw-grid-cell ${selected && cellKey(selected) === cellKey(cell) ? 'selected' : ''}`}
                onClick={() => setSelected(cell)} aria-label={title}>
                <title>{title}</title>
              </rect>;
            })}
            <text x={view.x + 18} y={view.y + MAP_HEIGHT - 18} className="mhw-map-caption">Detected event cells · cell footprints at native grid resolution</text>
          </svg>
          {basemapUnavailable && <div className="mhw-map-warning" role="status">Basemap tiles could not be loaded. Event overlays remain at their NOAA grid coordinates.</div>}
          <div className="mhw-map-legend">
            {layer === 'classification' && <><i className="legend-cell" /> Qualifying event cell</>}
            {layer === 'mean' && <><span>Mean event anomaly</span><i className="legend-gradient" /><span>0 to {meanMax.toFixed(2)}°C</span></>}
            {layer === 'peak' && <><span>Maximum event intensity</span><i className="legend-gradient" /><span>0 to {peakMax.toFixed(2)}°C</span></>}
            {layer === 'hotspots' && <><i className="legend-hotspot" /> Top detector hotspots <i className="legend-muted" /> Other event cells</>}
            <i className="legend-boundary" /> Analysis bounds
          </div>
          <div className="mhw-map-attribution">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a></div>
        </div>

        <aside className="mhw-cell-panel">
          <span className="overline">SELECTED GRID CELL</span>
          {selected && activeKeys.has(cellKey(selected)) ? <>
            <h3>{coordinate(selected.latitude, 'lat')}, {coordinate(selected.longitude, 'lon')}</h3>
            <small>Cell area {selected.area_km2?.toFixed(1) ?? '—'} km²</small>
            {selected.events.filter(isActive).map((event, i) => <div className="mhw-cell-event" key={`${event.start}-${i}`}>
              <b>{event.start} to {event.end}</b><span>{event.duration_days} day event · {event.exceedance_days ?? '—'} threshold exceedance days</span>
              <span>Mean event anomaly <strong>{event.mean_intensity_c.toFixed(2)}°C</strong></span>
              <span>Peak intensity <strong>{event.maximum_intensity_c.toFixed(2)}°C</strong></span>
              {finite(event.cumulative_intensity_c_days) && <span>Cumulative intensity {event.cumulative_intensity_c_days.toFixed(2)}°C·days</span>}
            </div>)}
          </> : <p>Click a colored grid cell to inspect its detector event metrics.</p>}
          <div className="mhw-daily-metric">
            <small>DAILY AREA-WEIGHTED COVERAGE · {date || 'DATE UNAVAILABLE'}</small>
            <b>{selectedDay ? `${selectedDay.percent_area_affected.toFixed(1)}%` : '—'}</b>
            <span>{selectedDay ? `${selectedDay.affected_cells.toLocaleString()} / ${selectedDay.valid_cells.toLocaleString()} valid cells` : 'Daily coverage not returned'}</span>
            {selectedDay && <span>{Math.round(selectedDay.affected_area_km2).toLocaleString()} km² estimated affected area</span>}
          </div>
        </aside>
      </div>

      {daily.length > 0 && <div className="mhw-timeline">
        <div className="mhw-timeline-head"><div><span className="overline">EVENT PROGRESSION</span><b>{date || 'Date unavailable'}</b></div>
          <div className="mhw-timeline-coverage">{selectedDay ? `${selectedDay.affected_cells.toLocaleString()} event cells · ${selectedDay.percent_area_affected.toFixed(1)}% area` : 'Daily coverage unavailable'}</div>
        </div>
        <input aria-label="Select analysis date" type="range" min="0" max={Math.max(daily.length - 1, 0)} value={safeDayIndex} disabled={daily.length < 2}
          onChange={event => { setDayIndex(Number(event.target.value)); setSelected(null); }} />
        <div className="mhw-date-ticks"><span>{daily[0]?.date}</span><span>{daily[daily.length - 1]?.date}</span></div>
      </div>}

      <details className="mhw-data-details"><summary>Data provenance and interpretation</summary>
        <div className="mhw-provenance-grid">
          <p><b>Target observations</b><span>{analysis.dataset || 'NOAA OISST v2.1'} · {analysis.dataset_id || targetProvenance?.dataset_id || 'dataset ID unavailable'} · preliminary near-real-time SST</span></p>
          <p><b>Historical baseline</b><span>NOAA OISST v2.1 Final · {analysis.baseline_period?.join('–') || '1991–2020'} · {analysis.baseline_dataset_id || 'dataset ID not returned by API'}</span></p>
          <p><b>Regional grid coverage</b><span>{analysis.target_valid_values?.toLocaleString() || '—'} valid of {analysis.target_total_values?.toLocaleString() || '—'} daily grid values{finite(analysis.target_missing_fraction) ? ` · ${(analysis.target_missing_fraction * 100).toFixed(1)}% missing/land in regional bbox` : ''}</span></p>
          <p><b>Baseline quality</b><span>{analysis.baseline_quality?.annual_chunks ?? '—'} annual chunks · {finite(analysis.baseline_quality?.missing_fraction) ? `${(analysis.baseline_quality.missing_fraction * 100).toFixed(1)}% missing/land in regional bbox` : 'coverage details unavailable'}</span></p>
          <p><b>Cell intensity</b><span>Mean and peak event anomalies relative to each cell's seasonal climatology. Absolute SST and daily climatology are not included in this detector response.</span></p>
          <p><b>Spatial encoding</b><span>Only qualifying event cells are returned by the detector. Non-event cells and per-cell missing locations are not encoded in this map.</span></p>
          <p><b>Method</b><span>{analysis.method || 'Detector method unavailable'} · 4-neighbour edge adjacency description; event component IDs are not returned.</span></p>
          {(targetProvenance?.url || analysis.target_url) && <p><b>Target source</b><a href={targetProvenance?.url || analysis.target_url} target="_blank" rel="noreferrer">Open NOAA retrieval URL</a></p>}
          {(baselineProvenance?.url || analysis.baseline_url) && <p><b>Baseline source</b><a href={baselineProvenance?.url || analysis.baseline_url} target="_blank" rel="noreferrer">Open NOAA baseline URL</a></p>}
        </div>
      </details>
      <p className="mhw-map-note">Cells show grid-scale detector classifications, not point measurements. Target SST is preliminary and may be revised. {analysis.limitations?.join(' ')}</p>
    </>}
  </section>;
}
