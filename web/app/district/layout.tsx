import type { Metadata } from "next";

export const metadata: Metadata = { title: "District forecast" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
