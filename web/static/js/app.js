/**
 * TravelDB: Fuel-Aware Transportation Decision Support System (NH 48 Corridor)
 * Modern Earthy Theme (Olive Green, Rusty Red & Warm Beige)
 * Features:
 *  - Watermark-free OSM & Esri map tiles
 *  - Null-safe initialization (locations and vehicles guaranteed to load)
 *  - Google Maps-style profile avatar & emergency contact manager
 *  - 3 Page Divisions: Journey Planner, Saved Trips & Notes, About & Legal
 *  - (i) Info icon and hover tooltips for every control and metric
 *  - Full CRUD Saved Trips Manager with editable travel checklists
 */

document.addEventListener("DOMContentLoaded", async () => {
    // =========================================================================
    // Global State
    // =========================================================================
    let map = null;
    let currentUser = null;
    let currentTripId = null;
    let currentRouteResult = null;
    let currentPolyline = null;
    let reroutePolyline = null;
    let originMarker = null;
    let destMarker = null;
    let stopMarkers = [];

    // Map layer groups
    const pumpsLayer = L.layerGroup();
    const blackspotsLayer = L.layerGroup();
    const weatherLayer = L.layerGroup();

    // Data lists
    let vehiclesList = [];
    let placesList = [];
    let activeObjective = "fastest";

    // =========================================================================
    // 1. Toast & Tooltip System
    // =========================================================================
    function showToast(message, type = "info") {
        const container = document.getElementById("toast-container");
        if (!container) return;
        const toast = document.createElement("div");
        toast.className = `toast ${type === "error" ? "toast-error" : type === "warning" ? "toast-warning" : ""}`;
        
        let icon = "fa-circle-check";
        if (type === "error") icon = "fa-triangle-exclamation";
        if (type === "warning") icon = "fa-bell";

        toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(-20px)";
            toast.style.transition = "all 0.3s ease";
            setTimeout(() => toast.remove(), 300);
        }, 3600);
    }

    function initTooltipSystem() {
        const popover = document.getElementById("tooltip-popover");
        const popText = document.getElementById("tooltip-text");
        if (!popover || !popText) return;

        let activeTrigger = null;

        document.addEventListener("mouseover", (e) => {
            const trigger = e.target.closest(".has-tooltip, .info-icon");
            if (!trigger) {
                if (popover.classList.contains("visible")) {
                    popover.classList.remove("visible");
                }
                return;
            }

            activeTrigger = trigger;
            const desc = trigger.getAttribute("data-desc") || trigger.closest(".has-tooltip")?.getAttribute("data-desc") || trigger.getAttribute("title");
            if (!desc) return;

            popText.textContent = desc;
            const rect = trigger.getBoundingClientRect();
            let top = rect.bottom + 8;
            let left = rect.left + (rect.width / 2) - 140;

            // Boundary adjustments
            if (left < 10) left = 10;
            if (left + 280 > window.innerWidth) left = window.innerWidth - 290;
            if (top + 80 > window.innerHeight) top = rect.top - 70;

            popover.style.top = `${top}px`;
            popover.style.left = `${left}px`;
            popover.classList.add("visible");
        });

        document.addEventListener("mouseout", (e) => {
            if (e.target.closest(".has-tooltip, .info-icon")) {
                popover.classList.remove("visible");
            }
        });
    }

    // =========================================================================
    // 2. Authentication & Profile Manager
    // =========================================================================
    async function initAuth() {
        // Load user from localStorage or fall back to seeded demo user
        const saved = localStorage.getItem("traveldb_user");
        if (saved) {
            try {
                currentUser = JSON.parse(saved);
            } catch (e) {
                currentUser = null;
            }
        }

        if (!currentUser) {
            // Fetch default demo user #1 from server
            try {
                const res = await fetch("/api/auth/profile?user_id=1");
                const data = await res.json();
                if (data.status === "success" && data.user) {
                    currentUser = data.user;
                    localStorage.setItem("traveldb_user", JSON.stringify(currentUser));
                }
            } catch (err) {
                console.warn("Could not load default profile:", err);
            }
        }

        updateHeaderProfileUI();
        setupAuthEvents();
    }

    function updateHeaderProfileUI() {
        if (!currentUser) return;
        
        // Calculate initials from Full Name (e.g., Asmit Sharma -> AS)
        const names = (currentUser.full_name || "Traveler").trim().split(" ");
        let initials = names[0] ? names[0][0].toUpperCase() : "T";
        if (names.length > 1) {
            initials += names[names.length - 1][0].toUpperCase();
        }

        const headAvatar = document.getElementById("header-avatar-initials");
        if (headAvatar) headAvatar.textContent = initials;

        const heroAvatar = document.getElementById("prof-hero-avatar");
        if (heroAvatar) heroAvatar.textContent = initials;

        const heroName = document.getElementById("prof-hero-name");
        if (heroName) heroName.textContent = currentUser.full_name;

        const heroUser = document.getElementById("prof-hero-user");
        if (heroUser) heroUser.textContent = `@${currentUser.username} • Traveler ID: #${currentUser.user_id}`;

        // Populate profile form inputs
        const fName = document.getElementById("prof-fullname");
        if (fName) fName.value = currentUser.full_name || "";
        const uName = document.getElementById("prof-username");
        if (uName) uName.value = currentUser.username || "";
        const age = document.getElementById("prof-age");
        if (age) age.value = currentUser.age || 20;
        const gender = document.getElementById("prof-gender");
        if (gender) gender.value = currentUser.gender || "Male";
        const phone = document.getElementById("prof-phone");
        if (phone) phone.value = currentUser.phone || "";
        const emPhone = document.getElementById("prof-emergency");
        if (emPhone) emPhone.value = currentUser.emergency_phone || "";
    }

    function setupAuthEvents() {
        // Open Profile Modal on Google Maps Avatar Click
        document.getElementById("btn-profile")?.addEventListener("click", () => {
            if (!currentUser) {
                document.getElementById("modal-auth")?.classList.add("open");
            } else {
                updateHeaderProfileUI();
                document.getElementById("modal-profile")?.classList.add("open");
            }
        });

        document.getElementById("btn-close-profile")?.addEventListener("click", () => {
            document.getElementById("modal-profile")?.classList.remove("open");
        });

        // Edit Profile Form Submit
        document.getElementById("form-edit-profile")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (!currentUser) return;

            const payload = {
                user_id: currentUser.user_id,
                full_name: document.getElementById("prof-fullname")?.value.trim(),
                age: parseInt(document.getElementById("prof-age")?.value),
                gender: document.getElementById("prof-gender")?.value,
                phone: document.getElementById("prof-phone")?.value.trim(),
                emergency_phone: document.getElementById("prof-emergency")?.value.trim()
            };

            try {
                const res = await fetch("/api/auth/profile", {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === "success") {
                    currentUser = data.user;
                    localStorage.setItem("traveldb_user", JSON.stringify(currentUser));
                    updateHeaderProfileUI();
                    document.getElementById("modal-profile")?.classList.remove("open");
                    showToast("Profile and emergency details updated successfully!");
                } else {
                    showToast(data.message || "Failed to update profile", "error");
                }
            } catch (err) {
                showToast("Server error updating profile", "error");
            }
        });

        // Log Out
        document.getElementById("btn-logout")?.addEventListener("click", () => {
            currentUser = null;
            localStorage.removeItem("traveldb_user");
            document.getElementById("modal-profile")?.classList.remove("open");
            document.getElementById("modal-auth")?.classList.add("open");
            showToast("Logged out successfully.", "warning");
        });

        // Auth Tabs Switch (Sign In vs Register)
        const tabLogin = document.getElementById("tab-btn-login");
        const tabReg = document.getElementById("tab-btn-register");
        const formLogin = document.getElementById("form-login");
        const formReg = document.getElementById("form-register");
        const authTitle = document.getElementById("auth-modal-title");

        tabLogin?.addEventListener("click", () => {
            tabLogin.classList.add("active");
            tabReg.classList.remove("active");
            formLogin.classList.add("active");
            formReg.classList.remove("active");
            if (authTitle) authTitle.textContent = "Sign In to TravelDB";
        });

        tabReg?.addEventListener("click", () => {
            tabReg.classList.add("active");
            tabLogin.classList.remove("active");
            formReg.classList.add("active");
            formLogin.classList.remove("active");
            if (authTitle) authTitle.textContent = "Create Traveler Profile";
        });

        // Quick Demo Login Fill Button
        document.getElementById("btn-quick-demo-login")?.addEventListener("click", () => {
            const u = document.getElementById("login-username");
            const p = document.getElementById("login-password");
            if (u) u.value = "demo_driver";
            if (p) p.value = "password123";
        });

        // Login Form Submit
        formLogin?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const username = document.getElementById("login-username")?.value.trim();
            const password = document.getElementById("login-password")?.value.trim();

            try {
                const res = await fetch("/api/auth/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username, password })
                });
                const data = await res.json();
                if (data.status === "success" && data.user) {
                    currentUser = data.user;
                    localStorage.setItem("traveldb_user", JSON.stringify(currentUser));
                    updateHeaderProfileUI();
                    document.getElementById("modal-auth")?.classList.remove("open");
                    showToast(`Welcome back, ${currentUser.full_name}!`);
                    loadSavedTrips();
                } else {
                    showToast(data.message || "Invalid credentials", "error");
                }
            } catch (err) {
                showToast("Connection error logging in", "error");
            }
        });

        // Register Form Submit
        formReg?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const payload = {
                username: document.getElementById("reg-username")?.value.trim(),
                password: document.getElementById("reg-password")?.value.trim(),
                full_name: document.getElementById("reg-fullname")?.value.trim(),
                age: parseInt(document.getElementById("reg-age")?.value),
                gender: document.getElementById("reg-gender")?.value,
                phone: document.getElementById("reg-phone")?.value.trim(),
                emergency_phone: document.getElementById("reg-emergency")?.value.trim()
            };

            try {
                const res = await fetch("/api/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === "success" && data.user) {
                    currentUser = data.user;
                    localStorage.setItem("traveldb_user", JSON.stringify(currentUser));
                    updateHeaderProfileUI();
                    document.getElementById("modal-auth")?.classList.remove("open");
                    showToast(`Welcome to TravelDB, ${currentUser.full_name}! Registration complete.`);
                    loadSavedTrips();
                } else {
                    showToast(data.message || "Registration failed", "error");
                }
            } catch (err) {
                showToast("Connection error registering", "error");
            }
        });
    }

    // =========================================================================
    // 3. Tab Navigation Controller (3 Page Divisions)
    // =========================================================================
    function initTabs() {
        const tabs = document.querySelectorAll(".nav-tab");
        tabs.forEach(tab => {
            tab.addEventListener("click", () => {
                const targetTabId = tab.getAttribute("data-tab");
                if (!targetTabId) return;

                // Deactivate all tabs & divisions
                tabs.forEach(t => t.classList.remove("active"));
                document.querySelectorAll(".page-division").forEach(p => p.classList.remove("active"));

                // Activate selected
                tab.classList.add("active");
                const targetDiv = document.getElementById(targetTabId);
                if (targetDiv) targetDiv.classList.add("active");

                // If switching to map planner, refresh Leaflet container bounds
                if (targetTabId === "tab-planner" && map) {
                    setTimeout(() => map.invalidateSize(), 150);
                }

                // If switching to saved trips, reload list
                if (targetTabId === "tab-saved") {
                    loadSavedTrips();
                }
            });
        });

        // Shortcut button in Saved Trips to go to Planner
        document.getElementById("btn-new-trip-shortcut")?.addEventListener("click", () => {
            document.querySelector('.nav-tab[data-tab="tab-planner"]')?.click();
        });
    }

    // =========================================================================
    // 4. Map & Highway Overlays Initialization
    // =========================================================================
    function initMap() {
        // Center along Chennai - Vellore highway corridor (NH 48)
        map = L.map("map", {
            zoomControl: true,
            attributionControl: true
        }).setView([12.96, 79.70], 10);

        // 1. OpenStreetMap Standard (Crisp official road network, zero watermark)
        const osmStandard = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        });

        // 2. OpenStreetMap Humanitarian (High contrast highway layout)
        const osmHot = L.tileLayer("https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png", {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        });

        // 3. Esri World Street Map (Commercial highway navigation)
        const esriStreets = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
            attribution: 'Tiles &copy; Esri &mdash; World Street Map',
            maxZoom: 18
        });

        // 4. Esri Satellite Imagery
        const esriSatellite = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
            attribution: 'Tiles &copy; Esri &mdash; Aerial Photography',
            maxZoom: 18
        });

        // Default: OpenStreetMap Standard
        osmStandard.addTo(map);

        // Layer Switcher Control (Top Right)
        const baseMaps = {
            "🗺️ OpenStreetMap": osmStandard,
            "🛣️ High-Contrast Highway": osmHot,
            "🏙️ Esri Street Navigation": esriStreets,
            "🛰️ Satellite Photography": esriSatellite
        };

        const overlayMaps = {
            "⛽ Fuel Stations (240+)": pumpsLayer,
            "⚠️ Fatal Blackspots (10)": blackspotsLayer,
            "🌤️ Live Weather Grid": weatherLayer
        };

        L.control.layers(baseMaps, overlayMaps, { position: "topright" }).addTo(map);

        pumpsLayer.addTo(map);
        blackspotsLayer.addTo(map);
        weatherLayer.addTo(map);

        // Synchronize sidebar checkboxes with map layers
        document.getElementById("layer-pumps")?.addEventListener("change", (e) => {
            if (e.target.checked) map.addLayer(pumpsLayer);
            else map.removeLayer(pumpsLayer);
        });

        document.getElementById("layer-blackspots")?.addEventListener("change", (e) => {
            if (e.target.checked) map.addLayer(blackspotsLayer);
            else map.removeLayer(blackspotsLayer);
        });

        document.getElementById("layer-weather")?.addEventListener("change", (e) => {
            if (e.target.checked) map.addLayer(weatherLayer);
            else map.removeLayer(weatherLayer);
        });
    }

    // =========================================================================
    // 5. Data Loaders (Stats, Vehicles, Places, Spatial Layers)
    // =========================================================================
    async function loadStats() {
        try {
            const res = await fetch("/api/stats");
            const data = await res.json();
            if (data.status === "success") {
                const s = data.stats;
                const setT = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
                setT("stat-nodes", s.nodes.toLocaleString());
                setT("stat-edges", s.directed_edges.toLocaleString());
                setT("stat-pumps", s.fuel_stations.toLocaleString());
                setT("stat-blackspots", s.blackspots);
                setT("stat-weather", `${s.weather_observations} pts`);
            }
        } catch (err) {
            console.error("Failed to load stats:", err);
        }
    }

    async function loadVehicles() {
        try {
            const res = await fetch("/api/vehicles");
            const data = await res.json();
            if (data.status === "success") {
                vehiclesList = data.vehicles;
                const select = document.getElementById("select-vehicle");
                if (select) {
                    select.innerHTML = "";
                    vehiclesList.forEach(v => {
                        const opt = document.createElement("option");
                        opt.value = v.vehicle_id;
                        opt.textContent = `${v.make_model} (${v.fuel_type.toUpperCase()})`;
                        select.appendChild(opt);
                    });
                }
                updateVehicleSpecs();
            }
        } catch (err) {
            console.error("Failed to load vehicles:", err);
        }
    }

    function updateVehicleSpecs() {
        const select = document.getElementById("select-vehicle");
        if (!select) return;
        const vId = parseInt(select.value);
        const v = vehiclesList.find(x => x.vehicle_id === vId);
        if (v) {
            const setT = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            setT("spec-tank", `${v.tank_capacity_l} L`);
            setT("spec-mileage", `${v.rated_mileage_kmpl} km/L`);
            setT("spec-fuel", v.fuel_type.toUpperCase());

            const slider = document.getElementById("slider-initial-fuel");
            if (slider) {
                slider.max = v.tank_capacity_l;
                const curVal = parseFloat(slider.value);
                const pct = Math.min(100, Math.max(5, (curVal / v.tank_capacity_l) * 100));
                const fill = document.getElementById("tank-visual-fill");
                if (fill) fill.style.width = `${pct}%`;
            }
        }
    }

    async function loadPlaces() {
        try {
            const res = await fetch("/api/places");
            const data = await res.json();
            if (data.status === "success") {
                placesList = data.places;
                const origSel = document.getElementById("select-origin");
                const destSel = document.getElementById("select-destination");
                if (!origSel || !destSel) return;

                origSel.innerHTML = "";
                destSel.innerHTML = "";

                placesList.forEach(p => {
                    const opt1 = document.createElement("option");
                    opt1.value = `${p.lat},${p.lon}`;
                    opt1.textContent = p.name;
                    origSel.appendChild(opt1);

                    const opt2 = document.createElement("option");
                    opt2.value = `${p.lat},${p.lon}`;
                    opt2.textContent = p.name;
                    destSel.appendChild(opt2);
                });

                // Default: Poonamallee -> Damal
                origSel.selectedIndex = 0; // Poonamallee
                destSel.selectedIndex = 4; // Damal
            }
        } catch (err) {
            console.error("Failed to load places:", err);
        }
    }

    async function loadLayers() {
        // Blackspots
        try {
            const res = await fetch("/api/layers/blackspots");
            const data = await res.json();
            if (data.features) {
                blackspotsLayer.clearLayers();
                data.features.forEach(f => {
                    const [lon, lat] = f.geometry.coordinates;
                    const p = f.properties;
                    const icon = L.divIcon({
                        className: "blackspot-icon",
                        html: `<div style="background:#B7410E; color:#FFFFFF; border-radius:50%; width:24px; height:24px; display:flex; align-items:center; justify-content:center; border:2px solid #FFFFFF; box-shadow:0 2px 6px rgba(0,0,0,0.3); font-size:11px;"><i class="fa-solid fa-triangle-exclamation"></i></div>`,
                        iconSize: [24, 24]
                    });
                    const marker = L.marker([lat, lon], { icon }).bindPopup(`
                        <div style="font-family:'Inter',sans-serif; min-width:180px;">
                            <strong style="color:#B7410E; font-size:13px;"><i class="fa-solid fa-triangle-exclamation"></i> ${p.name}</strong>
                            <div style="font-size:11px; margin-top:4px; color:#5E6353;">Source: MoRTH India (${p.year})</div>
                            <div style="font-size:11px; color:#24261F; margin-top:2px;">Corridor High-Fatality Blackspot</div>
                        </div>
                    `);
                    blackspotsLayer.addLayer(marker);
                });
            }
        } catch (e) {
            console.error("Failed to load blackspots:", e);
        }

        // Fuel Stations
        try {
            const res = await fetch("/api/layers/fuel-stations");
            const data = await res.json();
            if (data.features) {
                pumpsLayer.clearLayers();
                data.features.forEach(f => {
                    const [lon, lat] = f.geometry.coordinates;
                    const p = f.properties;
                    const marker = L.circleMarker([lat, lon], {
                        radius: 5,
                        fillColor: "#556B2F",
                        color: "#FFFFFF",
                        weight: 1.5,
                        opacity: 1,
                        fillOpacity: 0.85
                    }).bindPopup(`
                        <div style="font-family:'Inter',sans-serif; min-width:190px;">
                            <strong style="color:#3B4D20; font-size:13px;"><i class="fa-solid fa-gas-pump"></i> ${p.name}</strong>
                            <div style="font-size:11px; color:#5E6353; margin-top:3px;">Brand: <strong>${p.brand || 'Retail'}</strong></div>
                            <div style="font-size:11px; color:#24261F;">Petrol: <strong>₹ ${p.petrol_price}/L</strong> &bull; Diesel: <strong>₹ ${p.diesel_price}/L</strong></div>
                        </div>
                    `);
                    pumpsLayer.addLayer(marker);
                });
            }
        } catch (e) {
            console.error("Failed to load fuel stations:", e);
        }

        // Weather Grid
        try {
            const res = await fetch("/api/layers/weather");
            const data = await res.json();
            if (data.features) {
                weatherLayer.clearLayers();
                data.features.forEach(f => {
                    const [lon, lat] = f.geometry.coordinates;
                    const p = f.properties;
                    const marker = L.circleMarker([lat, lon], {
                        radius: 7,
                        fillColor: "#8F9779",
                        color: "#FFFFFF",
                        weight: 1.5,
                        fillOpacity: 0.6
                    }).bindPopup(`
                        <div style="font-family:'Inter',sans-serif; min-width:160px;">
                            <strong style="color:#3B4D20; font-size:12px;"><i class="fa-solid fa-cloud-sun"></i> Weather Feed</strong>
                            <div style="font-size:11px; margin-top:4px;">Temp: <strong>${p.temp_c}°C</strong> | Wind: <strong>${p.wind_kph} km/h</strong></div>
                            <div style="font-size:11px; color:#5E6353;">Rain: <strong>${p.rain_mm} mm</strong> (Drag Factor: ${p.drag_factor}x)</div>
                        </div>
                    `);
                    weatherLayer.addLayer(marker);
                });
            }
        } catch (e) {
            console.error("Failed to load weather layer:", e);
        }
    }

    // =========================================================================
    // 6. Route Planning & Gas Station Problem Solver
    // =========================================================================
    async function computeFuelRoute() {
        const origSel = document.getElementById("select-origin");
        const destSel = document.getElementById("select-destination");
        const vehSel = document.getElementById("select-vehicle");
        const sInit = document.getElementById("slider-initial-fuel");
        const sRes = document.getElementById("slider-reserve");
        const chkBlack = document.getElementById("check-avoid-blackspots");

        if (!origSel || !destSel || !origSel.value || !destSel.value) {
            showToast("Please select origin and destination.", "warning");
            return;
        }

        const [oLat, oLon] = origSel.value.split(",").map(Number);
        const [dLat, dLon] = destSel.value.split(",").map(Number);
        const vehicleId = parseInt(vehSel.value);
        const initialFuel = parseFloat(sInit.value);
        const reserveFuel = parseFloat(sRes.value);
        const avoidBlackspots = chkBlack.checked;

        const payload = {
            user_id: currentUser ? currentUser.user_id : 1,
            origin: [oLat, oLon],
            destination: [dLat, dLon],
            vehicle_id: vehicleId,
            initial_fuel_l: initialFuel,
            initial_fuel: initialFuel,
            reserve_l: reserveFuel,
            reserve_fuel: reserveFuel,
            objective: activeObjective,
            avoid_blackspots: avoidBlackspots
        };

        const calcBtn = document.getElementById("btn-calculate");
        if (calcBtn) {
            calcBtn.disabled = true;
            calcBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Solving Route...`;
        }

        try {
            const res = await fetch("/api/fuel-plan", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (data.status === "success" && data.plan) {
                const plan = data.plan;
                currentTripId = plan.trip_id;
                currentRouteResult = plan;
                renderRoute(plan);
                showToast("Route and refuel schedule computed successfully!");
            } else {
                showToast(data.message || "Route calculation error", "error");
            }
        } catch (err) {
            console.error("Route error:", err);
            showToast("Server communication error", "error");
        } finally {
            if (calcBtn) {
                calcBtn.disabled = false;
                calcBtn.innerHTML = `<i class="fa-solid fa-magnifying-glass-location"></i> Compute Fuel-Safe Route`;
            }
        }
    }

    function renderRoute(data) {
        // Robust extraction whether data is full response or plan object
        const plan = data.plan || data;
        const coords = plan.polyline; // Array of [lat, lon]
        if (!coords || !Array.isArray(coords) || coords.length === 0) {
            console.error("Invalid coordinates in plan:", plan);
            return;
        }

        // Clear previous polylines & markers
        if (currentPolyline) map.removeLayer(currentPolyline);
        if (reroutePolyline) map.removeLayer(reroutePolyline);
        if (originMarker) map.removeLayer(originMarker);
        if (destMarker) map.removeLayer(destMarker);
        stopMarkers.forEach(m => map.removeLayer(m));
        stopMarkers = [];

        // Polyline
        currentPolyline = L.polyline(coords, {
            color: "#556B2F",
            weight: 5,
            opacity: 0.9,
            lineJoin: "round"
        }).addTo(map);

        map.fitBounds(currentPolyline.getBounds(), { padding: [60, 60] });

        // Origin Marker (Olive Green flag)
        const oCoord = coords[0];
        originMarker = L.marker(oCoord, {
            icon: L.divIcon({
                html: `<div style="background:#556B2F; color:#FFFFFF; border-radius:50%; width:28px; height:28px; display:flex; align-items:center; justify-content:center; border:2px solid #FFFFFF; box-shadow:0 3px 8px rgba(0,0,0,0.3); font-size:13px;"><i class="fa-solid fa-play"></i></div>`,
                iconSize: [28, 28]
            })
        }).bindPopup("<strong>Origin Point</strong>").addTo(map);

        // Destination Marker (Rusty Red checkered flag)
        const dCoord = coords[coords.length - 1];
        destMarker = L.marker(dCoord, {
            icon: L.divIcon({
                html: `<div style="background:#B7410E; color:#FFFFFF; border-radius:50%; width:28px; height:28px; display:flex; align-items:center; justify-content:center; border:2px solid #FFFFFF; box-shadow:0 3px 8px rgba(0,0,0,0.3); font-size:13px;"><i class="fa-solid fa-flag-checkered"></i></div>`,
                iconSize: [28, 28]
            })
        }).bindPopup("<strong>Destination Point</strong>").addTo(map);

        // Refuel Stops
        const callout = document.getElementById("refuel-callout-box");
        const stops = plan.refuel_stops || [];
        if (stops.length > 0) {
            stops.forEach((s, idx) => {
                const marker = L.marker([s.lat, s.lon], {
                    icon: L.divIcon({
                        className: "pulse-refuel-pin",
                        iconSize: [22, 22]
                    })
                }).bindPopup(`
                    <div style="font-family:'Inter',sans-serif; min-width:210px;">
                        <span style="background:#FEF3C7; color:#92400E; font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; text-transform:uppercase;">Scheduled Refuel Stop #${idx + 1}</span>
                        <h4 style="margin:4px 0 2px; color:#24261F; font-size:13px;">${s.station_name}</h4>
                        <div style="font-size:11px; color:#5E6353;">At Corridor KM ${s.at_distance_km}</div>
                        <div style="font-size:11px; margin-top:4px;">Arrive with: <strong>${s.arrival_fuel_l} L</strong></div>
                        <div style="font-size:11px;">Add: <strong style="color:#556B2F;">${s.refuel_liters_added} L</strong> (Full Tank)</div>
                        <div style="font-size:12px; font-weight:700; color:#B7410E; margin-top:2px;">Est. Cost: ₹ ${Math.round(s.estimated_cost_inr).toLocaleString()}</div>
                    </div>
                `).addTo(map);
                stopMarkers.push(marker);
            });

            // Populate callout
            const s0 = stops[0];
            const nameEl = document.getElementById("callout-station-name");
            const detEl = document.getElementById("callout-details");
            if (nameEl) nameEl.textContent = `${s0.station_name} • KM ${s0.at_distance_km}`;
            if (detEl) detEl.innerHTML = `Arrive with ${s0.arrival_fuel_l} L &bull; Add <strong>${s0.refuel_liters_added} L</strong> to full tank &bull; Est. Cost: <strong>₹ ${Math.round(s0.estimated_cost_inr).toLocaleString()}</strong>`;
            if (callout) callout.style.display = "flex";
        } else {
            if (callout) callout.style.display = "none";
        }

        // Populate Results Drawer
        const rCard = document.getElementById("results-card");
        if (rCard) rCard.style.display = "flex";

        const setT = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        const distance = plan.distance_km ?? plan.total_distance_km ?? plan.total_km ?? 0;
        const duration = plan.eta_minutes ?? plan.total_duration_min ?? plan.duration_min ?? 0;
        const fuel = plan.total_fuel_needed_l ?? plan.total_fuel_needed_litres ?? plan.fuel_needed_l ?? 0;
        const stopsCount = plan.refuel_stops_count ?? (plan.refuel_stops ? plan.refuel_stops.length : 0);
        const cost = plan.total_refuel_cost_inr ?? plan.total_cost_inr ?? 0;

        setT("res-distance", `${Number(distance).toFixed(1)} km`);
        setT("res-duration", `${Math.round(duration)} mins`);
        setT("res-fuel", `${Number(fuel).toFixed(2)} L`);
        setT("res-stops", `${stopsCount} ${stopsCount === 1 ? 'Stop' : 'Stops'}`);
        setT("res-cost", `₹ ${Math.round(cost).toLocaleString()}`);

        const tagFeas = document.getElementById("tag-feasibility");
        if (tagFeas) {
            tagFeas.textContent = plan.feasible ? "FEASIBLE" : "INFEASIBLE";
            tagFeas.style.background = plan.feasible ? "#DCFCE7" : "#FEE2E2";
            tagFeas.style.color = plan.feasible ? "#166534" : "#991B1B";
        }

        // Turn-by-turn guidance
        const turns = plan.turn_instructions || plan.instructions || [];
        setT("turns-count", `${turns.length} turns`);
        const tContainer = document.getElementById("turns-container");
        if (tContainer) {
            tContainer.innerHTML = "";
            turns.forEach(t => {
                const div = document.createElement("div");
                div.className = "turn-step";
                div.textContent = t;
                tContainer.appendChild(div);
            });
        }
    }

    // =========================================================================
    // 7. Saved Trips Manager (CRUD)
    // =========================================================================
    async function loadSavedTrips() {
        if (!currentUser) return;
        try {
            const res = await fetch(`/api/saved-trips?user_id=${currentUser.user_id}`);
            const data = await res.json();
            if (data.status === "success") {
                renderSavedTrips(data.saved_trips || []);
            }
        } catch (err) {
            console.error("Error loading saved trips:", err);
        }
    }

    function renderSavedTrips(trips) {
        const container = document.getElementById("saved-trips-list");
        const countBadge = document.getElementById("badge-saved-count");
        if (countBadge) countBadge.textContent = trips.length;
        if (!container) return;

        if (trips.length === 0) {
            container.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 3rem; background:#FFFFFF; border: 2px dashed var(--c-beige-border); border-radius: var(--radius-lg);">
                    <i class="fa-solid fa-bookmark" style="font-size: 2.5rem; color: var(--c-olive-soft); margin-bottom: 0.8rem;"></i>
                    <h3 style="color: var(--c-olive-deep); font-family: var(--font-heading); font-size: 1.15rem;">No Saved Trip Plans Yet</h3>
                    <p style="color: var(--c-text-muted); font-size: 0.85rem; max-width: 420px; margin: 0.4rem auto 1.2rem;">
                        Use the Journey Planner to compute a fuel-aware corridor itinerary, then click "Save This Trip" to bookmark it here with your custom travel notes!
                    </p>
                    <button class="btn btn-primary" id="btn-goto-planner-empty">
                        <i class="fa-solid fa-compass"></i> Open Journey Planner
                    </button>
                </div>
            `;
            document.getElementById("btn-goto-planner-empty")?.addEventListener("click", () => {
                document.querySelector('.nav-tab[data-tab="tab-planner"]')?.click();
            });
            return;
        }

        container.innerHTML = "";
        trips.forEach(t => {
            const dateStr = new Date(t.created_at).toLocaleDateString("en-IN", {
                day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"
            });

            const card = document.createElement("div");
            card.className = "saved-trip-card";
            card.innerHTML = `
                <div class="st-card-top">
                    <div>
                        <h3 class="st-title">${t.trip_title}</h3>
                        <span class="st-date"><i class="fa-regular fa-clock"></i> ${dateStr}</span>
                    </div>
                    <span class="corridor-tag">${t.vehicle_name}</span>
                </div>

                <div class="st-endpoints">
                    <div><i class="fa-solid fa-location-dot text-olive"></i> <strong>From:</strong> ${t.origin_name}</div>
                    <div><i class="fa-solid fa-flag-checkered text-rust"></i> <strong>To:</strong> ${t.destination_name}</div>
                </div>

                <div class="st-specs-row">
                    <div class="st-spec-box">
                        <div class="st-spec-lbl">Distance</div>
                        <div class="st-spec-val">${t.distance_km} km</div>
                    </div>
                    <div class="st-spec-box">
                        <div class="st-spec-lbl">Fuel Required</div>
                        <div class="st-spec-val">${t.fuel_liters} L</div>
                    </div>
                    <div class="st-spec-box">
                        <div class="st-spec-lbl">Refuel Cost</div>
                        <div class="st-spec-val text-rust">₹ ${Math.round(t.estimated_cost_inr).toLocaleString()}</div>
                    </div>
                </div>

                <div class="st-notes-box">
                    <div class="st-notes-title"><i class="fa-solid fa-note-sticky text-olive"></i> Travel Notes:</div>
                    <p class="st-notes-body">${t.trip_notes || '<em>No notes added. Click edit to add departure checklists or reminders.</em>'}</p>
                </div>

                <div class="st-actions">
                    <button class="btn btn-secondary btn-edit-trip" data-id="${t.saved_trip_id}" data-title="${t.trip_title}" data-notes="${encodeURIComponent(t.trip_notes || '')}">
                        <i class="fa-solid fa-pen-to-square"></i> Edit Notes
                    </button>
                    <button class="btn btn-warning btn-delete-trip" data-id="${t.saved_trip_id}">
                        <i class="fa-solid fa-trash-can"></i> Delete
                    </button>
                </div>
            `;
            container.appendChild(card);
        });

        // Attach action events
        container.querySelectorAll(".btn-edit-trip").forEach(btn => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-id");
                const title = btn.getAttribute("data-title");
                const notes = decodeURIComponent(btn.getAttribute("data-notes"));

                const idInput = document.getElementById("edit-saved-trip-id");
                const titleInput = document.getElementById("edit-trip-title");
                const notesInput = document.getElementById("edit-trip-notes");

                if (idInput) idInput.value = id;
                if (titleInput) titleInput.value = title;
                if (notesInput) notesInput.value = notes;

                document.getElementById("modal-edit-notes")?.classList.add("open");
            });
        });

        container.querySelectorAll(".btn-delete-trip").forEach(btn => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-id");
                if (!confirm(`Are you sure you want to delete saved trip #${id}?`)) return;

                try {
                    const res = await fetch(`/api/saved-trips/${id}`, { method: "DELETE" });
                    const data = await res.json();
                    if (data.status === "success") {
                        showToast("Saved trip deleted.", "warning");
                        loadSavedTrips();
                    } else {
                        showToast(data.message || "Failed to delete trip", "error");
                    }
                } catch (e) {
                    showToast("Error deleting trip", "error");
                }
            });
        });
    }

    function setupSavedTripModalEvents() {
        // Open Save Trip Modal from Drawer
        const openSaveBtn = document.getElementById("btn-save-trip-drawer");
        openSaveBtn?.addEventListener("click", () => {
            if (!currentRouteResult) {
                showToast("Please calculate a route first before saving.", "warning");
                return;
            }

            const origSel = document.getElementById("select-origin");
            const destSel = document.getElementById("select-destination");
            const vehSel = document.getElementById("select-vehicle");

            const origName = origSel?.options[origSel.selectedIndex]?.text || "Origin";
            const destName = destSel?.options[destSel.selectedIndex]?.text || "Destination";
            const vehName = vehSel?.options[vehSel.selectedIndex]?.text || "Vehicle";

            const dist = currentRouteResult.distance_km ?? currentRouteResult.total_distance_km ?? currentRouteResult.total_km ?? 0;
            const fuel = currentRouteResult.total_fuel_needed_l ?? currentRouteResult.total_fuel_needed_litres ?? currentRouteResult.fuel_needed_l ?? 0;
            const cost = currentRouteResult.total_refuel_cost_inr ?? currentRouteResult.total_cost_inr ?? 0;
            const stops = currentRouteResult.refuel_stops_count ?? (currentRouteResult.refuel_stops ? currentRouteResult.refuel_stops.length : 0);

            const setT = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            setT("save-summary-endpoints", `${origName} → ${destName}`);
            setT("save-summary-vehicle", vehName);
            setT("save-summary-distance-fuel", `${Number(dist).toFixed(1)} km • ${Number(fuel).toFixed(2)} L`);
            setT("save-summary-stops-cost", `${stops} Stops • ₹ ${Math.round(cost).toLocaleString()}`);

            document.getElementById("modal-save-trip")?.classList.add("open");
        });

        document.getElementById("btn-close-save-modal")?.addEventListener("click", () => {
            document.getElementById("modal-save-trip")?.classList.remove("open");
        });

        document.getElementById("btn-cancel-save-trip")?.addEventListener("click", () => {
            document.getElementById("modal-save-trip")?.classList.remove("open");
        });

        // Form Submit: Save Trip
        document.getElementById("form-save-trip")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (!currentRouteResult) return;

            const origSel = document.getElementById("select-origin");
            const destSel = document.getElementById("select-destination");
            const vehSel = document.getElementById("select-vehicle");

            const dist = currentRouteResult.distance_km ?? currentRouteResult.total_distance_km ?? currentRouteResult.total_km ?? 0;
            const fuel = currentRouteResult.total_fuel_needed_l ?? currentRouteResult.total_fuel_needed_litres ?? currentRouteResult.fuel_needed_l ?? 0;
            const cost = currentRouteResult.total_refuel_cost_inr ?? currentRouteResult.total_cost_inr ?? 0;
            const stops = currentRouteResult.refuel_stops_count ?? (currentRouteResult.refuel_stops ? currentRouteResult.refuel_stops.length : 0);

            const payload = {
                user_id: currentUser ? currentUser.user_id : 1,
                trip_id: currentTripId,
                trip_title: document.getElementById("save-trip-title")?.value.trim() || "Corridor Trip",
                origin_name: origSel?.options[origSel.selectedIndex]?.text || "Origin",
                destination_name: destSel?.options[destSel.selectedIndex]?.text || "Destination",
                vehicle_name: vehSel?.options[vehSel.selectedIndex]?.text || "Standard Vehicle",
                distance_km: parseFloat(dist),
                fuel_liters: parseFloat(fuel),
                refuel_stops: parseInt(stops),
                estimated_cost_inr: parseFloat(cost),
                trip_notes: document.getElementById("save-trip-notes")?.value.trim() || ""
            };

            try {
                const res = await fetch("/api/saved-trips", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === "success") {
                    document.getElementById("modal-save-trip")?.classList.remove("open");
                    showToast("Trip plan saved to your profile with travel notes!");
                    loadSavedTrips();
                } else {
                    showToast(data.message || "Failed to save trip", "error");
                }
            } catch (err) {
                showToast("Server error saving trip", "error");
            }
        });

        // Edit Notes Modal
        document.getElementById("btn-close-edit-notes")?.addEventListener("click", () => {
            document.getElementById("modal-edit-notes")?.classList.remove("open");
        });
        document.getElementById("btn-cancel-edit-notes")?.addEventListener("click", () => {
            document.getElementById("modal-edit-notes")?.classList.remove("open");
        });

        document.getElementById("form-edit-notes")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const id = document.getElementById("edit-saved-trip-id")?.value;
            const trip_title = document.getElementById("edit-trip-title")?.value.trim();
            const trip_notes = document.getElementById("edit-trip-notes")?.value.trim();

            try {
                const res = await fetch(`/api/saved-trips/${id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ trip_title, trip_notes })
                });
                const data = await res.json();
                if (data.status === "success") {
                    document.getElementById("modal-edit-notes")?.classList.remove("open");
                    showToast("Trip travel notes updated successfully!");
                    loadSavedTrips();
                } else {
                    showToast(data.message || "Failed to update notes", "error");
                }
            } catch (err) {
                showToast("Server error updating notes", "error");
            }
        });
    }

    // =========================================================================
    // 8. Simulation & Hazard Reporting
    // =========================================================================
    function setupSimulationEvents() {
        // Simulate Low Fuel Reroute
        document.getElementById("btn-sim-low-fuel")?.addEventListener("click", async () => {
            if (!currentTripId) {
                showToast("Please compute an initial route first.", "warning");
                return;
            }

            showToast("Simulating low fuel alarm (2.0 L remaining)... Re-optimizing remaining path...", "warning");

            const payload = {
                current_coords: [12.9348, 79.8450], // Sunguvarchatram on NH 48
                current_fuel_l: 2.0,
                trigger_reason: "low_fuel"
            };

            try {
                const res = await fetch(`/api/trip/${currentTripId}/reroute`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === "success" && data.reroute) {
                    const newPlan = data.reroute.new_plan || data.reroute.reroute_plan;
                    if (newPlan && newPlan.polyline) {
                        if (reroutePolyline) map.removeLayer(reroutePolyline);
                        reroutePolyline = L.polyline(newPlan.polyline, {
                            color: "#B7410E",
                            weight: 6,
                            dashArray: "8, 8",
                            opacity: 0.95
                        }).addTo(map);

                        map.fitBounds(reroutePolyline.getBounds(), { padding: [50, 50] });
                        showToast("Emergency reroute computed! Diverted to nearest pump. Logged to REROUTE_EVENT.");
                    }
                } else {
                    showToast(data.message || "Reroute failed", "error");
                }
            } catch (err) {
                console.error("Simulation error:", err);
                showToast("Error executing simulation reroute", "error");
            }
        });

        // Hazard Report Modal
        document.getElementById("btn-open-report")?.addEventListener("click", () => {
            document.getElementById("modal-report")?.classList.add("open");
        });
        document.getElementById("btn-close-report")?.addEventListener("click", () => {
            document.getElementById("modal-report")?.classList.remove("open");
        });
        document.getElementById("btn-cancel-report")?.addEventListener("click", () => {
            document.getElementById("modal-report")?.classList.remove("open");
        });

        document.getElementById("form-hazard-report")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const payload = {
                user_id: currentUser ? currentUser.user_id : 1,
                hazard_type: document.getElementById("rep-type")?.value,
                severity: document.getElementById("rep-severity")?.value,
                description: document.getElementById("rep-desc")?.value.trim(),
                lat: 12.95,
                lon: 79.80
            };

            try {
                const res = await fetch("/api/reports", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === "success") {
                    document.getElementById("modal-report")?.classList.remove("open");
                    showToast("Hazard report submitted to MySQL database. Thank you for contributing!");
                } else {
                    showToast(data.message || "Failed to submit report", "error");
                }
            } catch (err) {
                showToast("Error submitting report", "error");
            }
        });
    }

    // =========================================================================
    // 9. Startup UI Event Listeners
    // =========================================================================
    function setupControls() {
        // Vehicle select change
        document.getElementById("select-vehicle")?.addEventListener("change", updateVehicleSpecs);

        // Sliders
        const sInit = document.getElementById("slider-initial-fuel");
        sInit?.addEventListener("input", (e) => {
            const val = parseFloat(e.target.value);
            const valPill = document.getElementById("val-initial-fuel");
            if (valPill) valPill.textContent = `${val.toFixed(1)} L`;

            const vId = parseInt(document.getElementById("select-vehicle")?.value);
            const v = vehiclesList.find(x => x.vehicle_id === vId);
            if (v) {
                const pct = Math.min(100, Math.max(5, (val / v.tank_capacity_l) * 100));
                const fill = document.getElementById("tank-visual-fill");
                if (fill) fill.style.width = `${pct}%`;
            }
        });

        const sRes = document.getElementById("slider-reserve");
        sRes?.addEventListener("input", (e) => {
            const valPill = document.getElementById("val-reserve");
            if (valPill) valPill.textContent = `${parseFloat(e.target.value).toFixed(1)} L`;
        });

        // Objective buttons (Auto recalculates on click!)
        document.querySelectorAll(".btn-obj").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".btn-obj").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                activeObjective = btn.getAttribute("data-obj") || "fastest";
                computeFuelRoute();
            });
        });

        // Avoid Blackspots checkbox change
        document.getElementById("check-avoid-blackspots")?.addEventListener("change", computeFuelRoute);

        // Origin & Destination dropdown changes
        document.getElementById("select-origin")?.addEventListener("change", computeFuelRoute);
        document.getElementById("select-destination")?.addEventListener("change", computeFuelRoute);

        // Calculate Route Button
        document.getElementById("btn-calculate")?.addEventListener("click", computeFuelRoute);

        // Turn guidance toggle
        document.getElementById("btn-toggle-turns")?.addEventListener("click", () => {
            const list = document.getElementById("turns-list") || document.getElementById("turns-container");
            const icon = document.getElementById("turns-icon");
            if (list) {
                const isHidden = list.style.display === "none";
                list.style.display = isHidden ? "flex" : "none";
                if (icon) icon.className = isHidden ? "fa-solid fa-chevron-up" : "fa-solid fa-chevron-down";
            }
        });

        // Close results button
        document.getElementById("btn-close-results")?.addEventListener("click", () => {
            const rCard = document.getElementById("results-card");
            if (rCard) rCard.style.display = "none";
        });
    }

    // =========================================================================
    // 10. Master Execution Sequence
    // =========================================================================
    initTooltipSystem();
    initMap();
    initTabs();
    await initAuth();
    await loadStats();
    await loadVehicles();
    await loadPlaces();
    await loadLayers();
    setupControls();
    setupSavedTripModalEvents();
    setupSimulationEvents();
    loadSavedTrips();

    // Auto-calculate default corridor route on startup so user sees full interface immediately!
    computeFuelRoute();
});
