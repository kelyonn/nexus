import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import TokenBootstrap from "./TokenBootstrap";

export const metadata: Metadata = {
  title: "Nexus Dashboard",
  description: "Local control panel for Nexus-managed apps.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <TokenBootstrap />
        <header className="topbar">
          <span className="brand">Nexus Dashboard</span>
          <nav>
            <Link href="/">Overview</Link>
            <Link href="/synclog">GitOps Log</Link>
          </nav>
        </header>
        <main className="content">{children}</main>
      </body>
    </html>
  );
}
