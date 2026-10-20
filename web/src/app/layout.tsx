import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Listening Room · Spotify Review Intelligence",
  description:
    "An evidence-led view of Spotify reviews, pipeline coverage, product priorities, and model evaluation.",
  icons: {
    icon: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' rx='20' fill='%2318241d'/%3E%3Cpath d='M10 24v-6a10 10 0 0 1 20 0v6M10 22h4v9h-4zM26 22h4v9h-4z' fill='none' stroke='%23c7f57a' stroke-width='2.5' stroke-linejoin='round'/%3E%3C/svg%3E",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
