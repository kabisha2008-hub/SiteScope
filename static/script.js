"use strict";

document.addEventListener("DOMContentLoaded", () => {
  /* ========================================
       1. SCROLL REVEAL ANIMATIONS
    ======================================== */

  const revealItems = document.querySelectorAll(".reveal");

  if ("IntersectionObserver" in window) {
    const revealObserver = new IntersectionObserver(
      (entries, observer) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.12,
        rootMargin: "0px 0px -30px 0px",
      },
    );

    revealItems.forEach((element, index) => {
      element.style.transitionDelay = `${(index % 3) * 100}ms`;

      revealObserver.observe(element);
    });
  } else {
    revealItems.forEach((element) => {
      element.classList.add("is-visible");
    });
  }

  /* ========================================
       2. FLOATING CARD MOUSE EFFECT
    ======================================== */

  const floatingCards = document.querySelectorAll(
    ".about-glass-card, .preview-card",
  );

  const supportsHover = window.matchMedia(
    "(hover: hover) and (pointer: fine)",
  ).matches;

  if (supportsHover) {
    floatingCards.forEach((card) => {
      card.addEventListener("mousemove", (event) => {
        const rect = card.getBoundingClientRect();

        const x = (event.clientX - rect.left) / rect.width - 0.5;

        const y = (event.clientY - rect.top) / rect.height - 0.5;

        card.style.transform = `perspective(900px) rotateX(${-y * 4}deg) rotateY(${x * 4}deg) translateY(-4px)`;
      });

      card.addEventListener("mouseleave", () => {
        card.style.transform = "";
      });
    });
  }

  /* ========================================
       3. NAVBAR SCROLL EFFECT
    ======================================== */

  const navbar = document.querySelector(".navbar, .site-nav, header nav");

  const updateNavbar = () => {
    if (!navbar) return;

    navbar.classList.toggle("scrolled", window.scrollY > 25);
  };

  updateNavbar();

  window.addEventListener("scroll", updateNavbar, {
    passive: true,
  });

  /* ========================================
       4. MOBILE NAVIGATION
    ======================================== */

  const menuToggle = document.querySelector(
    "[data-menu-toggle], .menu-toggle, .nav-toggle",
  );

  const navLinks = document.querySelector("[data-nav-links], .nav-links");

  if (menuToggle && navLinks) {
    menuToggle.setAttribute("aria-expanded", "false");

    menuToggle.addEventListener("click", () => {
      const isOpen = navLinks.classList.toggle("is-open");

      menuToggle.classList.toggle("is-active", isOpen);

      menuToggle.setAttribute("aria-expanded", String(isOpen));
    });

    navLinks.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        navLinks.classList.remove("is-open");
        menuToggle.classList.remove("is-active");
        menuToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  /* ========================================
       5. SEO ANALYZER LOADING FEEDBACK
    ======================================== */

  const scanForms = document.querySelectorAll("[data-scan-form]");

  scanForms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
        return;
      }

      const submitButton = form.querySelector(
        'button[type="submit"], input[type="submit"]',
      );

      if (!submitButton || submitButton.disabled) {
        return;
      }

      submitButton.dataset.originalText =
        submitButton.tagName === "INPUT"
          ? submitButton.value
          : submitButton.textContent;

      submitButton.disabled = true;
      submitButton.classList.add("is-loading");

      if (submitButton.tagName === "INPUT") {
        submitButton.value = "Analyzing website...";
      } else {
        submitButton.textContent = "Analyzing website...";
      }

      /*
       * The form continues submitting to Flask.
       * The backend performs the actual SEO analysis.
       */
    });
  });

  /* ========================================
       6. REPORT DELETE CONFIRMATION
    ======================================== */

  const deleteForms = document.querySelectorAll("[data-delete-form]");

  deleteForms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      const confirmed = window.confirm(
        "Are you sure you want to delete this report? This action cannot be undone.",
      );

      if (!confirmed) {
        event.preventDefault();
      }
    });
  });

  /* ========================================
       7. FAQ ACCORDION
    ======================================== */

  const faqItems = document.querySelectorAll(".faq-item");

  faqItems.forEach((item) => {
    item.addEventListener("toggle", () => {
      if (!item.open) return;

      faqItems.forEach((otherItem) => {
        if (otherItem !== item) {
          otherItem.open = false;
        }
      });
    });
  });

  /* ========================================
       8. SMOOTH SCROLL FOR PAGE LINKS
    ======================================== */

  document.querySelectorAll('a[href*="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      const href = link.getAttribute("href");

      if (!href || href === "#") return;

      let target;

      try {
        const url = new URL(href, window.location.href);

        if (url.pathname !== window.location.pathname || url.hash.length < 2) {
          return;
        }

        target = document.querySelector(
          `#${CSS.escape(decodeURIComponent(url.hash.slice(1)))}`,
        );
      } catch {
        return;
      }

      if (!target) return;

      event.preventDefault();

      target.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
        block: "start",
      });

      history.replaceState(null, "", href);
    });
  });

  /* ========================================
       9. INPUT FOCUS ANIMATIONS
    ======================================== */

  const formInputs = document.querySelectorAll(
    "input:not([type='hidden']), textarea, select",
  );

  formInputs.forEach((input) => {
    input.addEventListener("focus", () => {
      input.classList.add("is-focused");
    });

    input.addEventListener("blur", () => {
      input.classList.remove("is-focused");
    });
  });

  /* ========================================
       10. PASSWORD VISIBILITY TOGGLE
       Works when a toggle button exists.
    ======================================== */

  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-password-toggle");

      const passwordInput = document.getElementById(targetId);

      if (!passwordInput) return;

      const showPassword = passwordInput.type === "password";

      passwordInput.type = showPassword ? "text" : "password";

      button.setAttribute(
        "aria-label",
        showPassword ? "Hide password" : "Show password",
      );
    });
  });

  /* ========================================
       11. BUTTON RIPPLE EFFECT
    ======================================== */

  document.querySelectorAll(".button, button").forEach((button) => {
    button.addEventListener("pointerdown", (event) => {
      if (button.disabled) return;

      const rect = button.getBoundingClientRect();

      button.style.setProperty("--ripple-x", `${event.clientX - rect.left}px`);

      button.style.setProperty("--ripple-y", `${event.clientY - rect.top}px`);

      button.classList.remove("ripple-active");

      // Restart the CSS animation.
      void button.offsetWidth;

      button.classList.add("ripple-active");
    });
  });

  /* ========================================
       12. CURRENT YEAR IN FOOTER
    ======================================== */

  const yearElement = document.querySelector("[data-current-year]");

  if (yearElement) {
    yearElement.textContent = new Date().getFullYear();
  }

  /* ========================================
       13. REDUCED MOTION ACCESSIBILITY
    ======================================== */

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.documentElement.classList.add("reduce-motion");
  }

  console.log("SiteScope UI initialized successfully.");
});
