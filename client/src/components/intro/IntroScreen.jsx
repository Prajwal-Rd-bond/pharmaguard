import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion, useAnimation, useReducedMotion } from 'framer-motion';
import ShieldLogo from './ShieldLogo';
import StatusTicker from './StatusTicker';
import {
  introConfig,
  gridVariants,
  moleculeVariants,
  wordmarkContainerVariants,
  wordmarkLetterVariants,
  taglineVariants,
  underlineVariants,
  exitCircleVariants
} from './intro.variants';

export default function IntroScreen() {
  const navigate = useNavigate();
  const shouldReduceMotion = useReducedMotion();
  const [isSkipping, setIsSkipping] = useState(false);
  const [isExiting, setIsExiting] = useState(false);
  const controls = useAnimation();
  const timeoutRef = useRef(null);

  const location = useLocation();

  // Check if already seen
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (sessionStorage.getItem('pg_intro_seen') === '1' && !params.has('intro')) {
      navigate('/login', { replace: true });
    }
  }, [navigate, location.search]);

  const startExit = async (skip = false) => {
    if (isExiting) return;
    setIsExiting(true);
    setIsSkipping(skip);
    
    // Expand circle
    await controls.start('visible');
    
    // Navigate
    completeIntro();
  };

  const completeIntro = () => {
    sessionStorage.setItem('pg_intro_seen', '1');
    navigate('/login', { replace: true });
  };

  useEffect(() => {
    if (shouldReduceMotion) {
      const t = setTimeout(() => {
        completeIntro();
      }, 1500); // short wait then skip
      return () => clearTimeout(t);
    }

    // Normal timeline
    const exitTimer = setTimeout(() => {
      startExit(false);
    }, introConfig.timings.exitDelay * 1000);

    // 6s fallback
    timeoutRef.current = setTimeout(() => {
      completeIntro();
    }, 6000);

    return () => {
      clearTimeout(exitTimer);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [shouldReduceMotion]);

  // Handle escape/enter to skip
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' || e.key === 'Enter') {
        startExit(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isExiting]);

  const params = new URLSearchParams(location.search);
  if (sessionStorage.getItem('pg_intro_seen') === '1' && !params.has('intro')) {
    return null;
  }

  // Preload login
  useEffect(() => {
    import('../../pages/Login.jsx').catch(() => {});
  }, []);

  return (
    <motion.div 
      className="fixed inset-0 flex flex-col items-center justify-center overflow-hidden"
      style={{ backgroundColor: introConfig.colors.bg }}
      role="status"
      aria-label="PharmaGuard Intro Sequence"
      exit={{ opacity: 0, transition: { duration: 0.2 } }}
    >
      {/* Background Lab Grid */}
      {!shouldReduceMotion && (
        <motion.div
          className="absolute inset-0 z-0 pointer-events-none"
          variants={gridVariants}
          initial="hidden"
          animate="visible"
          style={{
            backgroundImage: `
              linear-gradient(to right, rgba(226, 232, 240, 0.4) 1px, transparent 1px),
              linear-gradient(to bottom, rgba(226, 232, 240, 0.4) 1px, transparent 1px)
            `,
            backgroundSize: '32px 32px',
            backgroundPosition: 'center center'
          }}
        />
      )}

      {/* Radial Teal Tint */}
      <div 
        className="absolute inset-0 z-0 pointer-events-none"
        style={{
          background: `radial-gradient(circle at center, rgba(20,184,166,0.08) 0%, transparent 60%)`
        }}
      />

      {/* Corner Registration Marks (Hidden on small screens) */}
      {!shouldReduceMotion && (
        <div className="hidden sm:block absolute inset-0 z-0 pointer-events-none">
          <div className="absolute top-8 left-8 w-6 h-6 border-t-2 border-l-2 border-slate-300 opacity-50" />
          <div className="absolute top-8 right-8 w-6 h-6 border-t-2 border-r-2 border-slate-300 opacity-50" />
          <div className="absolute bottom-8 left-8 w-6 h-6 border-b-2 border-l-2 border-slate-300 opacity-50" />
          <div className="absolute bottom-8 right-8 w-6 h-6 border-b-2 border-r-2 border-slate-300 opacity-50" />
        </div>
      )}

      {/* Decorative Molecules */}
      {!shouldReduceMotion && (
        <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden" aria-hidden="true">
          <motion.svg className="absolute top-12 left-12 w-24 h-24" variants={moleculeVariants} initial="hidden" animate="visible">
            <path d="M50 10 L85 30 L85 70 L50 90 L15 70 L15 30 Z" fill="none" stroke={introConfig.colors.primary} strokeWidth="2" />
          </motion.svg>
          <motion.svg className="absolute bottom-12 right-12 w-32 h-32" variants={moleculeVariants} initial="hidden" animate="visible">
            <path d="M50 10 L85 30 L85 70 L50 90 L15 70 L15 30 Z" fill="none" stroke={introConfig.colors.secondary} strokeWidth="2" />
          </motion.svg>
        </div>
      )}

      {/* Main Content */}
      <div className="relative z-10 flex flex-col items-center">
        <ShieldLogo />

        <div className="mt-6 flex flex-col items-center">
          <motion.h1 
            className="font-semibold flex"
            style={{ 
              fontFamily: '"Inter", "Plus Jakarta Sans", sans-serif',
              fontSize: 'clamp(28px, 6vw, 56px)'
            }}
            variants={wordmarkContainerVariants}
            initial="hidden"
            animate="visible"
          >
            {'Pharma'.split('').map((char, i) => (
              <motion.span key={`p-${i}`} variants={wordmarkLetterVariants} style={{ color: introConfig.colors.text }}>
                {char}
              </motion.span>
            ))}
            {'Guard'.split('').map((char, i) => (
              <motion.span key={`g-${i}`} variants={wordmarkLetterVariants} style={{ color: introConfig.colors.primary }}>
                {char}
              </motion.span>
            ))}
          </motion.h1>

          <div className="relative mt-2">
            <motion.p 
              className="text-[10px] sm:text-xs uppercase tracking-[0.08em]"
              style={{ color: introConfig.colors.slate }}
              variants={taglineVariants}
              initial="hidden"
              animate="visible"
            >
              SAFER DRUGS · SMARTER DECISIONS
            </motion.p>
            <motion.div 
              className="absolute -bottom-2 left-0 right-0 h-[1px]"
              style={{ backgroundColor: introConfig.colors.primary, transformOrigin: 'center' }}
              variants={underlineVariants}
              initial="hidden"
              animate="visible"
            />
          </div>
        </div>

        {!shouldReduceMotion && <StatusTicker />}
      </div>

      {/* Version Tag */}
      <div className="hidden sm:block absolute bottom-6 left-6 z-10 opacity-30 pointer-events-none">
        <span className="font-mono text-xs" style={{ color: introConfig.colors.text }}>
          v1.0 · Pharmacovigilance Suite
        </span>
      </div>

      {/* Skip Button */}
      {!shouldReduceMotion && (
        <motion.button
          className="absolute bottom-8 right-8 z-20 text-sm font-medium hover:opacity-100 transition-opacity focus:outline-none focus:ring-2 focus:ring-teal-500 rounded px-3 py-1"
          style={{ color: introConfig.colors.slate, opacity: 0.5 }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.5 }}
          transition={{ delay: 0.5, duration: 0.5 }}
          onClick={() => startExit(true)}
        >
          Skip intro &rarr;
        </motion.button>
      )}

      {/* Circular Exit Transition */}
      {!shouldReduceMotion && (
        <motion.div
          className="absolute inset-0 z-50 pointer-events-none"
          style={{ backgroundColor: introConfig.colors.primary }}
          custom={{ isSkip: isSkipping }}
          variants={exitCircleVariants}
          initial="hidden"
          animate={controls}
        />
      )}
    </motion.div>
  );
}

