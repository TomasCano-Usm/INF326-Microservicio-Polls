import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Conversaciones | Polls",
  description: "Chat de canales y encuestas para INF326",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
