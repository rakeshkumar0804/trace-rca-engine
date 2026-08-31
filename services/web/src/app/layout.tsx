import './globals.css';
import React from 'react';

export const metadata = {
  title: 'TRACE — Root Cause Autonomous Engine',
  description: 'Autonomous RCA agent powered by deterministic falsification & evidence grounding',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#080c14] text-slate-100 min-h-screen flex flex-col antialiased">
        {children}
      </body>
    </html>
  );
}
