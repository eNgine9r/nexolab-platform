import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NEXOLAB — Laboratory IoT Platform",
  description: "Cold chain, smart locker and laboratory monitoring control center.",
  applicationName: "NEXOLAB",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#06142a",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="uk" className="h-full antialiased">
      <body className="min-h-full bg-[#06142a] font-sans">{children}</body>
    </html>
  );
}
