export const introConfig = {
  colors: {
    bg: '#F7FAFC',
    primary: '#0D9488', // Teal
    secondary: '#2563EB', // Medical Blue
    text: '#0F172A', // Deep Navy
    highlight: '#CCFBF1', // Soft Mint
    slate: '#64748B', // Secondary text
    alert: '#F43F5E', // Coral alert
  },
  timings: {
    // Stage 1: Lab Canvas
    gridFadeDuration: 0.6,
    gridStagger: 0.05,
    moleculeDrawDuration: 1.0,

    // Stage 2: Logo Build
    logoTraceDelay: 0.6,
    logoTraceDuration: 0.9,
    shieldFillDelay: 1.4,
    shieldFillDuration: 0.5,
    capsuleDropDelay: 1.2,
    capsuleDropSpring: { stiffness: 180, damping: 16 },
    ecgSweepDelay: 1.6,
    ecgSweepDuration: 0.6,

    // Stage 3: Wordmark
    wordmarkDelay: 1.9,
    wordmarkStagger: 0.04,
    taglineDelay: 2.3,

    // Stage 4: Ticker
    tickerDelay: 2.9,
    tickerCycle: 0.4, // 400ms per text

    // Stage 5: Exit (Circular Reveal)
    exitDelay: 4.1,
    exitDuration: 0.8,
    
    totalIntroTime: 5000,
    skipExitDuration: 0.4,
    reducedMotionFade: 0.3
  },
  easing: [0.22, 1, 0.36, 1],
};

export const gridVariants = {
  hidden: { opacity: 0 },
  visible: { 
    opacity: 1, 
    transition: { duration: introConfig.timings.gridFadeDuration, ease: introConfig.easing } 
  }
};

export const moleculeVariants = {
  hidden: { pathLength: 0, opacity: 0 },
  visible: { 
    pathLength: 1,
    opacity: 0.06, // 6% opacity per spec
    transition: { 
      pathLength: { duration: introConfig.timings.moleculeDrawDuration, ease: introConfig.easing },
      opacity: { duration: 0.3 }
    } 
  }
};

export const shieldOutlineVariants = {
  hidden: { pathLength: 0, opacity: 0 },
  visible: { 
    pathLength: 1, 
    opacity: 1, 
    transition: { 
      delay: introConfig.timings.logoTraceDelay, 
      duration: introConfig.timings.logoTraceDuration, 
      ease: 'easeInOut' 
    } 
  }
};

export const shieldFillVariants = {
  hidden: { opacity: 0 },
  visible: { 
    opacity: 1,
    transition: { 
      delay: introConfig.timings.shieldFillDelay, 
      duration: introConfig.timings.shieldFillDuration, 
      ease: introConfig.easing 
    } 
  }
};

export const capsuleVariants = {
  hidden: { y: -50, opacity: 0, rotate: 0 },
  visible: { 
    y: 0, 
    opacity: 1, 
    rotate: 45,
    transition: { 
      delay: introConfig.timings.capsuleDropDelay,
      type: 'spring',
      stiffness: introConfig.timings.capsuleDropSpring.stiffness,
      damping: introConfig.timings.capsuleDropSpring.damping
    }
  }
};

export const ecgLineVariants = {
  hidden: { pathLength: 0, stroke: introConfig.colors.primary },
  visible: { 
    pathLength: 1, 
    transition: { 
      delay: introConfig.timings.ecgSweepDelay, 
      duration: introConfig.timings.ecgSweepDuration, 
      ease: 'easeInOut' 
    } 
  }
};

export const wordmarkLetterVariants = {
  hidden: { y: 16, opacity: 0, filter: 'blur(4px)' },
  visible: { 
    y: 0, 
    opacity: 1, 
    filter: 'blur(0px)',
    transition: { ease: introConfig.easing }
  }
};

export const wordmarkContainerVariants = {
  hidden: {},
  visible: {
    transition: {
      delayChildren: introConfig.timings.wordmarkDelay,
      staggerChildren: introConfig.timings.wordmarkStagger,
    }
  }
};

export const taglineVariants = {
  hidden: { opacity: 0, y: 4 },
  visible: { 
    opacity: 1, 
    y: 0,
    transition: { 
      delay: introConfig.timings.taglineDelay,
      duration: 0.6,
      ease: introConfig.easing
    } 
  }
};

export const underlineVariants = {
  hidden: { scaleX: 0 },
  visible: { 
    scaleX: 1,
    transition: { 
      delay: introConfig.timings.taglineDelay,
      duration: 0.6,
      ease: introConfig.easing
    } 
  }
};

export const exitCircleVariants = {
  hidden: { clipPath: 'circle(0% at 50% 50%)' },
  visible: (custom) => ({
    clipPath: 'circle(150% at 50% 50%)',
    transition: {
      delay: custom?.isSkip ? 0 : introConfig.timings.exitDelay,
      duration: custom?.isSkip ? introConfig.timings.skipExitDuration : introConfig.timings.exitDuration,
      ease: 'easeInOut'
    }
  })
};

