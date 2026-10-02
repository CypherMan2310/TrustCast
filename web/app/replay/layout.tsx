import type { Metadata } from "next";

export const metadata: Metadata = { title: "Event replay" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
