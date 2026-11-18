import type { Metadata } from 'next';
import { Commissioner, JetBrains_Mono, Barlow_Semi_Condensed, Big_Shoulders } from 'next/font/google';
import { Analytics } from '@vercel/analytics/next';
import './globals.css';
import { Shell } from '@/components/layout/Shell';

const commissioner = Commissioner({ subsets: ['latin'], variable: '--font-commissioner', display: 'swap' });
const jetbrainsMono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '600', '700'], variable: '--font-jetbrains-mono', display: 'swap' });
const barlowSemiCondensed = Barlow_Semi_Condensed({ subsets: ['latin'], weight: ['500', '600', '700'], variable: '--font-barlow-sc', display: 'swap' });
const bigShoulders = Big_Shoulders({ subsets: ['latin'], weight: ['700', '800', '900'], variable: '--font-big-shoulders', display: 'swap' });

export const metadata: Metadata = {
  title: 'ScoutIQ — NBA Contract Intelligence',
  description: 'Explainable NBA contract valuation and cap simulation for front-office decision-making.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`h-full ${commissioner.variable} ${jetbrainsMono.variable} ${barlowSemiCondensed.variable} ${bigShoulders.variable}`} suppressHydrationWarning>
      <body className="h-full" suppressHydrationWarning>
        <Shell>{children}</Shell>
        <Analytics />
      </body>
    </html>
  );
}
