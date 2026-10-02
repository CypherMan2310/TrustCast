import type { Metadata } from "next";

export const metadata: Metadata = { title: "Who to trust" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
