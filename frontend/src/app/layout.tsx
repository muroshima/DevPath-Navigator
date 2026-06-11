import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DevPath Navigator",
  description: "Synthetic-data career navigator powered by Gemini + ADK.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className="font-sans antialiased h-full">{children}</body>
    </html>
  );
}
