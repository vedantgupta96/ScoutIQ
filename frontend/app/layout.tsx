import type { Metadata } from 'next';
import { Commissioner, Azeret_Mono } from 'next/font/google';
import { Analytics } from '@vercel/analytics/next';
import './globals.css';
import { Shell } from '@/components/layout/Shell';

const commissioner = Commissioner({ subsets: ['latin'], variable: '--font-commissioner', display: 'swap' });
const azeretMono = Azeret_Mono({ subsets: ['latin'], variable: '--font-azeret-mono', display: 'swap' });

export const metadata: Metadata = {
  title: 'ScoutIQ — NBA Contract Intelligence',
  description: 'Explainable NBA contract valuation and cap simulation for front-office decision-making.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`h-full ${commissioner.variable} ${azeretMono.variable}`} suppressHydrationWarning>
      <body className="h-full" suppressHydrationWarning>
        <Shell>{children}</Shell>
        <Analytics />
      </body>
    </html>
  );
}
