import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  introConfig,
  shieldOutlineVariants,
  shieldFillVariants,
  capsuleVariants,
  ecgLineVariants
} from './intro.variants';

export default function ShieldLogo() {
  const [ecgState, setEcgState] = useState('drawing'); // drawing, spike, check

  useEffect(() => {
    // Timing for ECG color/shape changes
    const totalDelay = introConfig.timings.ecgSweepDelay * 1000;
    
    const spikeTimer = setTimeout(() => {
      setEcgState('spike');
    }, totalDelay + (introConfig.timings.ecgSweepDuration * 1000) - 200);

    const checkTimer = setTimeout(() => {
      setEcgState('check');
    }, totalDelay + (introConfig.timings.ecgSweepDuration * 1000) + 400);

    return () => {
      clearTimeout(spikeTimer);
      clearTimeout(checkTimer);
    };
  }, []);

  return (
    <div className="relative flex items-center justify-center w-full h-full" style={{ width: 'clamp(120px, 28vw, 220px)', height: 'clamp(120px, 28vw, 220px)' }}>
      <motion.svg
        viewBox="0 0 100 120"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full drop-shadow-sm"
      >
        <defs>
          <linearGradient id="mintGradient" x1="0" y1="0" x2="100" y2="120" gradientUnits="userSpaceOnUse">
            <stop stopColor={introConfig.colors.highlight} />
            <stop offset="1" stopColor="white" stopOpacity="0.2" />
          </linearGradient>
          <linearGradient id="capsuleGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="50%" stopColor={introConfig.colors.primary} />
            <stop offset="50%" stopColor={introConfig.colors.secondary} />
          </linearGradient>
        </defs>

        {/* Shield Fill */}
        <motion.path
          d="M50 5 L90 20 V60 C90 90 50 115 50 115 C50 115 10 90 10 60 V20 L50 5 Z"
          fill="url(#mintGradient)"
          variants={shieldFillVariants}
          initial="hidden"
          animate="visible"
        />

        {/* Shield Outline */}
        <motion.path
          d="M50 5 L90 20 V60 C90 90 50 115 50 115 C50 115 10 90 10 60 V20 L50 5 Z"
          stroke={introConfig.colors.primary}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          variants={shieldOutlineVariants}
          initial="hidden"
          animate="visible"
        />

        {/* Capsule / Pill */}
        <motion.g
          variants={capsuleVariants}
          initial="hidden"
          animate="visible"
          style={{ originX: '50%', originY: '50%' }} // Center of SVG
        >
          {/* Pill is placed around center (50, 45) */}
          <rect x="42" y="25" width="16" height="40" rx="8" fill="url(#capsuleGrad)" />
        </motion.g>

        {/* ECG / Checkmark Sequence */}
        {ecgState !== 'check' && (
          <motion.path
            d="M20 75 L35 75 L42 60 L50 90 L58 75 L80 75"
            stroke={ecgState === 'spike' ? introConfig.colors.alert : introConfig.colors.primary}
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
            variants={ecgLineVariants}
            initial="hidden"
            animate="visible"
            className="transition-colors duration-300"
          />
        )}
        
        {ecgState === 'check' && (
          <motion.path
            d="M30 75 L45 90 L75 60"
            stroke={introConfig.colors.primary}
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
          />
        )}
      </motion.svg>
    </div>
  );
}

