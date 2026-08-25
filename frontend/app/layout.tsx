import type { Metadata } from "next";

import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Scientific Skill Transfer Agent",
  description: "Can an agent learn a technique from a paper and apply it to unseen data?",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Nav />
        {children}
      </body>
    </html>
  );
}
