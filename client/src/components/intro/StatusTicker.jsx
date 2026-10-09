import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { introConfig } from './intro.variants';
import { Check } from 'lucide-react';

const MESSAGES = [
  "Initializing secure environment…",
  "Loading pharmacovigilance engine…",
  "Verifying audit trail…",
  "Ready"
];

export default function StatusTicker() {
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    // Cycle text
    const interval = setInterval(() => {
      setCurrentIndex(prev => {
        if (prev < MESSAGES.length - 1) return prev + 1;
        clearInterval(interval);
        return prev;
      });
    }, introConfig.timings.tickerCycle * 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div 
      className="flex flex-col items-center mt-8 w-full max-w-[240px] mx-auto"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: introConfig.timings.tickerDelay, duration: 0.5 }}
      aria-live="polite"
    >
      <div className="h-6 flex items-center justify-center mb-2 overflow-hidden w-full relative">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentIndex}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.2 }}
            className="flex items-center gap-1.5 absolute"
          >
            {currentIndex > 0 && (
              <Check className="w-3 h-3" style={{ color: introConfig.colors.primary }} />
            )}
            <span 
              className="text-xs font-mono tracking-tight"
              style={{ color: introConfig.colors.slate }}
            >
              {MESSAGES[currentIndex]}
            </span>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Slim progress bar */}
      <div className="w-[200px] h-[3px] rounded-full bg-slate-200 overflow-hidden">
        <motion.div 
          className="h-full rounded-full relative overflow-hidden"
          style={{ backgroundColor: introConfig.colors.primary }}
          initial={{ width: '0%' }}
          animate={{ width: '100%' }}
          transition={{ 
            duration: (MESSAGES.length - 1) * introConfig.timings.tickerCycle,
            ease: 'linear'
          }}
        >
          {/* Shimmer effect */}
          <motion.div
            className="absolute top-0 bottom-0 w-10 bg-white opacity-30 skew-x-[-20deg]"
            animate={{ x: ['-200%', '300%'] }}
            transition={{ repeat: Infinity, duration: 1.5, ease: 'linear' }}
          />
        </motion.div>
      </div>
    </motion.div>
  );
}

