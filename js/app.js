const hiddenElements = document.querySelectorAll(".hidden");

const observer = new IntersectionObserver((entries) => {

    entries.forEach((entry) => {

        if (entry.isIntersecting) {

            entry.target.classList.add("show");

        }

    });

}, {
    threshold: 0.2
});

hiddenElements.forEach((element) => {

    observer.observe(element);

});
// ===========================
// Mobile Navigation
// ===========================

const menuButton = document.querySelector(".menu-toggle");
const nav = document.querySelector("nav");
const navLinks = document.querySelectorAll("nav a");

// Open / Close Menu
menuButton.addEventListener("click", () => {

    nav.classList.toggle("active");

});

// Close menu after clicking a navigation link
navLinks.forEach((link) => {

    link.addEventListener("click", () => {

        nav.classList.remove("active");

    });

});

// ===========================
// Tech Auto-Scroll — pauses on hover, resumes on leave
// ===========================

(function () {
    const track = document.getElementById("techTrack");
    const grid = document.getElementById("techGrid");

    if (!track || !grid) return;

    // Clone cards for seamless looping
    const cards = Array.from(track.children);
    cards.forEach(card => {
        const clone = card.cloneNode(true);
        track.appendChild(clone);
    });

    let offset = 0;
    let speed = 0.6; // pixels per frame (~36px/s at 60fps)
    let paused = false;
    let rafId = null;

    function animate() {
        if (!paused) {
            offset -= speed;
            // When we've scrolled past the first set, reset
            const singleSetWidth = track.scrollWidth / 2;
            if (Math.abs(offset) >= singleSetWidth) {
                offset += singleSetWidth;
            }
            track.style.transform = `translateX(${offset}px)`;
        }
        rafId = requestAnimationFrame(animate);
    }

    grid.addEventListener("mouseenter", () => { paused = true; });
    grid.addEventListener("mouseleave", () => { paused = false; });

    // Also pause on touch for mobile
    grid.addEventListener("touchstart", () => { paused = true; });
    grid.addEventListener("touchend", () => { paused = false; });

    // Start the loop
    rafId = requestAnimationFrame(animate);
})();