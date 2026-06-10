// ---- Background Demo Video - 2x speed ----
(function() {
  const video = document.getElementById('demoVideo');
  if (!video) return;

  video.playbackRate = 2.0;
  video.addEventListener('loadeddata', () => { video.playbackRate = 2.0; });

  // Fullscreen modal (click hero to watch at normal speed with sound)
  const modal = document.getElementById('videoModal');
  const videoFull = document.getElementById('demoVideoFull');
  const modalClose = document.getElementById('videoModalClose');

  if (!modal || !videoFull) return;

  function closeModal() {
    modal.classList.remove('active');
    videoFull.pause();
    video.play();
    document.body.style.overflow = '';
  }

  if (modalClose) {
    modalClose.addEventListener('click', (e) => {
      e.stopPropagation();
      closeModal();
    });
  }

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('active')) {
      closeModal();
    }
  });

  videoFull.addEventListener('click', (e) => {
    e.stopPropagation();
    if (videoFull.paused) {
      videoFull.play();
    } else {
      videoFull.pause();
    }
  });
})();

// ---- FAQ toggle ----
function toggleFaq(btn) {
  const item = btn.parentElement;
  const answer = item.querySelector('.faq-answer');
  const isOpen = item.classList.contains('open');

  document.querySelectorAll('.faq-item').forEach(i => {
    i.classList.remove('open');
    i.querySelector('.faq-answer').style.maxHeight = null;
  });

  if (!isOpen) {
    item.classList.add('open');
    answer.style.maxHeight = answer.scrollHeight + 'px';
  }
}

// ---- Subscribe - redirect to Stripe Checkout ----
async function subscribe(plan) {
  if (plan === 'enterprise') {
    window.location.href = 'mailto:support@phingr.com?subject=Enterprise%20Inquiry';
    return;
  }

  try {
    const resp = await fetch('/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan })
    });

    const data = await resp.json();
    if (data.url) {
      window.location.href = data.url;
    } else {
      alert('Something went wrong. Please try again.');
    }
  } catch (err) {
    alert('Unable to start checkout. Please try again later.');
  }
}

// ---- Smooth scroll for nav links ----
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    const href = this.getAttribute('href');
    if (href === '#') return;
    e.preventDefault();
    const target = document.querySelector(href);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth' });
      document.querySelector('.nav-links').classList.remove('open');
    }
  });
});
