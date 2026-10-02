import Link from "next/link";

export default function NotFound() {
  return (
    <div className="grid min-h-[60vh] place-items-center text-center">
      <div>
        <div className="text-gradient text-6xl font-bold tracking-tight">404</div>
        <h1 className="mt-3 text-xl font-semibold">This page is not on the map</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">The link may be old, or the district or event does not exist.</p>
        <Link href="/" className="brand-gradient mt-6 inline-flex h-9 items-center rounded-xl px-4 text-sm font-medium text-white shadow-md">
          Back to the forecast
        </Link>
      </div>
    </div>
  );
}
