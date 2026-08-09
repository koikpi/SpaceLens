import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SpaceLens — 磁盘空间分析器",
  description: "以交互式矩形树图快速发现占用磁盘空间的文件、目录和重复内容。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
