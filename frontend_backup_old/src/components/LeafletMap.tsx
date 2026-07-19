import "leaflet/dist/leaflet.css";
import { useEffect, useMemo } from "react";
import L from "leaflet";
import { MapContainer, Marker, Polyline, TileLayer, useMap } from "react-leaflet";

// Fix default marker icons (Leaflet expects assets at specific URLs).
const originIcon = new L.Icon({
  iconUrl:
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl:
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl:
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

// Tint destination pin with a subtle CSS hue rotation via className.
const destIcon = new L.Icon({
  ...originIcon.options,
  className: "leaflet-dest-marker",
});

export type LatLng = { lat: number; lng: number } | null;

export type LeafletMapProps = {
  origin: LatLng;
  destination: LatLng;
  originFallback: { lat: number; lng: number };
  destFallback: { lat: number; lng: number };
  onChange: (kind: "origin" | "destination", lat: number, lng: number) => void;
};

function FitBounds({ points }: { points: Array<[number, number]> }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 10);
      return;
    }
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds, { padding: [40, 40] });
  }, [map, points]);
  return null;
}

export default function LeafletMap({
  origin,
  destination,
  originFallback,
  destFallback,
  onChange,
}: LeafletMapProps) {
  const originPos: [number, number] = origin
    ? [origin.lat, origin.lng]
    : [originFallback.lat, originFallback.lng];
  const destPos: [number, number] = destination
    ? [destination.lat, destination.lng]
    : [destFallback.lat, destFallback.lng];

  const fitPoints = useMemo<Array<[number, number]>>(() => {
    const pts: Array<[number, number]> = [];
    if (origin) pts.push([origin.lat, origin.lng]);
    if (destination) pts.push([destination.lat, destination.lng]);
    if (pts.length === 0) pts.push(originPos, destPos);
    return pts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [origin?.lat, origin?.lng, destination?.lat, destination?.lng]);

  return (
    <div className="relative h-72 w-full overflow-hidden rounded-md border border-border">
      <style>{`.leaflet-dest-marker { filter: hue-rotate(140deg) saturate(1.2); }`}</style>
      <MapContainer
        center={originPos}
        zoom={7}
        scrollWheelZoom
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={fitPoints} />
        <Marker
          position={originPos}
          draggable
          icon={originIcon}
          eventHandlers={{
            dragend: (e) => {
              const m = e.target as L.Marker;
              const { lat, lng } = m.getLatLng();
              onChange("origin", lat, lng);
            },
          }}
        />
        <Marker
          position={destPos}
          draggable
          icon={destIcon}
          eventHandlers={{
            dragend: (e) => {
              const m = e.target as L.Marker;
              const { lat, lng } = m.getLatLng();
              onChange("destination", lat, lng);
            },
          }}
        />
        {origin && destination && (
          <Polyline
            positions={[originPos, destPos]}
            pathOptions={{ color: "#1e3a8a", weight: 2, dashArray: "6 6" }}
          />
        )}
      </MapContainer>
    </div>
  );
}
