"use strict";

/*
 * Mode B dashboard.
 * UI structure follows Mode A.
 * Backend operations remain Mode B's own DSA/API workflow.
 */

let dispatchMap = null;
let mapLayerGroup = null;
let gpsMarker = null;
let gpsReady = false;
let lastResult = null;

const byId = (id) => document.getElementById(id);

const SAMPLE_PAYLOAD = {
    severity: "Critical",
    traffic_profile: "normal",
    condition: "Cardiac Emergency",
    required_facility: "Emergency Department",
    patient_location: "Mode B Test Zone",
    area_address: "Mode B Test Emergency Location"
};

function setRuntime(message) {
    const node = byId("runtimeInfo");
    if (node) node.textContent = message;
}

function updateGpsStatus(message, kind = "info") {
    const node = byId("gpsStatus");
    if (!node) return;

    node.textContent = message;
    node.className =
        kind === "success" ? "info success" :
        kind === "warning" ? "info warning" : "info";
}

function updateGpsCoordinates(latitude, longitude, accuracy) {
    const node = byId("gpsCoordinates");
    if (!node) return;

    node.innerHTML =
        "Latitude: " + latitude.toFixed(6) + "<br>" +
        "Longitude: " + longitude.toFixed(6) + "<br>" +
        "Accuracy: approximately " + Math.round(accuracy) + " m";
}

function updateGpsMarker(latitude, longitude) {
    if (!dispatchMap || !window.L) return;

    const coordinates = [latitude, longitude];

    if (gpsMarker) {
        gpsMarker.setLatLng(coordinates);
    } else {
        gpsMarker = L.circleMarker(coordinates, {
            radius: 9,
            color: "#1769e0",
            fillColor: "#1769e0",
            fillOpacity: 0.85,
            weight: 3
        }).addTo(dispatchMap);

        gpsMarker.bindPopup(
            "<b>Current GPS Location</b><br>" +
            "Latitude: " + latitude.toFixed(6) + "<br>" +
            "Longitude: " + longitude.toFixed(6)
        );
    }
}

function handleGpsSuccess(position) {
    const latitude = position.coords.latitude;
    const longitude = position.coords.longitude;
    const accuracy = position.coords.accuracy;

    byId("latitude").value = latitude;
    byId("longitude").value = longitude;

    gpsReady = true;

    updateGpsCoordinates(latitude, longitude, accuracy);
    updateGpsStatus("GPS location detected successfully.", "success");
    updateGpsMarker(latitude, longitude);

    if (dispatchMap) {
        dispatchMap.setView([latitude, longitude], 15);
        dispatchMap.invalidateSize();
    }
}

function handleGpsError(error) {
    gpsReady = false;

    byId("latitude").value = "";
    byId("longitude").value = "";

    let message = "Unable to obtain GPS location.";

    if (error.code === 1) {
        message =
            "Location permission was denied. " +
            "Please allow location access in your browser.";
    } else if (error.code === 2) {
        message =
            "GPS location is unavailable. " +
            "Please check your device location settings.";
    } else if (error.code === 3) {
        message =
            "GPS location request timed out. Please try again.";
    }

    updateGpsStatus(message, "warning");

    const coordinates = byId("gpsCoordinates");
    if (coordinates) {
        coordinates.innerHTML =
            "Latitude: --<br>Longitude: --";
    }
}

/*
 * This is the only GPS request function.
 * It is called when Mode B opens and when the refresh button is clicked.
 */
function requestCurrentLocation() {
    if (!navigator.geolocation) {
        gpsReady = false;
        updateGpsStatus(
            "Browser geolocation is not supported.",
            "warning"
        );
        return;
    }

    gpsReady = false;
    updateGpsStatus("Requesting current GPS location...");

    const coordinates = byId("gpsCoordinates");
    if (coordinates) {
        coordinates.innerHTML = "Latitude: --<br>Longitude: --";
    }

    navigator.geolocation.getCurrentPosition(
        handleGpsSuccess,
        handleGpsError,
        {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 0
        }
    );
}

function initializeMap() {
    if (dispatchMap !== null || !window.L) return;

    dispatchMap = L.map("dispatchMap").setView([0, 0], 2);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(dispatchMap);

    mapLayerGroup = L.layerGroup().addTo(dispatchMap);
}

function createRoleMarker(location, role, title) {
    if (!location) return null;

    const latitude = Number(location.latitude);
    const longitude = Number(location.longitude);

    if (
        !Number.isFinite(latitude) ||
        !Number.isFinite(longitude) ||
        Math.abs(latitude) > 90 ||
        Math.abs(longitude) > 180
    ) {
        return null;
    }

    const symbols = {
        ambulance: "A",
        patient: "P",
        hospital: "H"
    };

    const colors = {
        ambulance: "#1769e0",
        patient: "#e53935",
        hospital: "#1f9d55"
    };

    const icon = L.divIcon({
        className: "",
        html:
            `<div style="width:32px;height:32px;display:flex;` +
            `align-items:center;justify-content:center;border-radius:50%;` +
            `background:${colors[role] || "#1769e0"};color:#fff;` +
            `font-weight:800;border:3px solid #fff;` +
            `box-shadow:0 2px 7px #0003">` +
            `${symbols[role] || "●"}</div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 16]
    });

    return L.marker([latitude, longitude], { icon }).bindPopup(
        `<b>${title}</b><br>` +
        `Latitude: ${latitude.toFixed(6)}<br>` +
        `Longitude: ${longitude.toFixed(6)}`
    );
}

function normalizePoints(points) {
    if (!Array.isArray(points)) return [];

    return points.map((point) => {
        if (Array.isArray(point) && point.length >= 2) {
            return [Number(point[0]), Number(point[1])];
        }

        return [Number(point?.lat), Number(point?.lon)];
    }).filter(([latitude, longitude]) =>
        Number.isFinite(latitude) &&
        Number.isFinite(longitude) &&
        Math.abs(latitude) <= 90 &&
        Math.abs(longitude) <= 180
    );
}

function formatNumber(value, digits = 2) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "Unavailable";
    }

    const number = Number(value);
    return Number.isFinite(number)
        ? number.toFixed(digits)
        : "Unavailable";
}

function hasNumericValue(value) {
    return value !== null &&
        value !== undefined &&
        value !== "" &&
        Number.isFinite(Number(value));
}

function drawLeg(leg, title) {
    if (!leg || !mapLayerGroup) return [];

    const collected = [];
    const staticPoints = normalizePoints(leg.static_points);
    const dynamicPoints = normalizePoints(leg.dynamic_points);

    const routeObjective = String(
        leg.route_objective || ""
    ).toLowerCase();

    const selectedRouteLabel =
        typeof leg.selected_route_label === "string" &&
        leg.selected_route_label.trim()
            ? leg.selected_route_label
            : routeObjective === "time"
                ? "Time-aware A*"
                : "Dynamic A*";

    const selectedDistance = hasNumericValue(
        leg.selected_distance_km
    )
        ? leg.selected_distance_km
        : leg.dynamic_distance_km;

    let selectedTime = leg.selected_time_minutes;

    if (!hasNumericValue(selectedTime)) {
        if (
            routeObjective === "time" &&
            hasNumericValue(leg.time_time_minutes)
        ) {
            selectedTime = leg.time_time_minutes;
        } else {
            selectedTime = leg.dynamic_time_minutes;
        }
    }

    // Display the distance-based Static A* comparison route.
    if (staticPoints.length > 1) {
        L.polyline(staticPoints, {
            color: "#68798b",
            weight: 4,
            opacity: 0.88,
            dashArray: "8,7"
        }).bindPopup(
            `<b>${title} - Static A*</b><br>` +
            `Distance: ${formatNumber(leg.static_distance_km, 3)} km`
        ).addTo(mapLayerGroup);

        collected.push(...staticPoints);
    }

    // Display the selected route for this journey leg.
    // Leg 1 uses Dynamic A*; Leg 2 uses Time-aware A*.
    if (dynamicPoints.length > 1) {
        L.polyline(dynamicPoints, {
            color: "#ff6b21",
            weight: 5,
            opacity: 0.93
        }).bindPopup(
            `<b>${title} - ${selectedRouteLabel}</b><br>` +
            `Distance: ${formatNumber(selectedDistance, 3)} km<br>` +
            `Estimated time: ${formatNumber(selectedTime, 1)} min`
        ).addTo(mapLayerGroup);

        collected.push(...dynamicPoints);
    }

    return collected;
}

function renderMap(result) {
    initializeMap();

    if (!dispatchMap || !mapLayerGroup) {
        setRuntime(
            "Map could not initialize. Check Leaflet and internet connectivity."
        );
        return;
    }

    mapLayerGroup.clearLayers();

    const locations = result?.locations;
    const routes = result?.routes;

    if (!locations || !routes?.leg1 || !routes?.leg2) {
        setRuntime(
            "Mode B returned a recommendation, but route geometry is unavailable."
        );
        return;
    }

    const allCoordinates = [];

    [
        [locations.ambulance, "ambulance", "Ambulance"],
        [locations.patient, "patient", "Patient / emergency location"],
        [locations.hospital, "hospital", "Selected hospital"]
    ].forEach(([location, role, title]) => {
        const marker = createRoleMarker(location, role, title);

        if (!marker) return;

        marker.addTo(mapLayerGroup);
        allCoordinates.push([
            Number(location.latitude),
            Number(location.longitude)
        ]);
    });

    allCoordinates.push(
        ...drawLeg(routes.leg1, "Leg 1: Ambulance → Patient")
    );

    allCoordinates.push(
        ...drawLeg(routes.leg2, "Leg 2: Patient → Hospital")
    );

    if (allCoordinates.length > 0) {
        dispatchMap.fitBounds(
            L.latLngBounds(allCoordinates),
            { padding: [35, 35] }
        );
    }

    dispatchMap.invalidateSize();
}

function renderResult(result) {
    lastResult = result;

    const emergency = result.emergency || {};
    const dispatch = result.dispatch || {};
    const leg1 = result.routes?.leg1 || {};
    const leg2 = result.routes?.leg2 || {};

    byId("emergencyId").textContent =
        emergency.emergency_id || "—";

    byId("priority").textContent =
        emergency.priority || emergency.severity || "—";

    byId("ambulance").textContent =
        dispatch.ambulance_id || "—";

    byId("ambulanceType").textContent =
        dispatch.ambulance_type || "—";

    byId("hospital").textContent =
        `${dispatch.hospital_id || "—"} - ` +
        `${dispatch.hospital_name || "Name unavailable"}`;

    byId("hospitalDistance").textContent =
        hasNumericValue(dispatch.hospital_distance)
            ? `${formatNumber(dispatch.hospital_distance, 3)} km`
            : "Route distance unavailable";

    byId("totalStatic").textContent =
        hasNumericValue(result.total_static_distance_km)
            ? `${formatNumber(result.total_static_distance_km, 3)} km`
            : "Unavailable";

    byId("totalDynamic").textContent =
        hasNumericValue(result.total_selected_distance_km)
            ? `${formatNumber(result.total_selected_distance_km, 3)} km`
            : "Unavailable";

    byId("trafficStatus").textContent =
        result.traffic_profile || "Configured Mode B road conditions";

    byId("dynamicStatus").textContent =
        dispatch.dynamic_status ||
        result.dispatch_status ||
        "Recommendation calculated";

    byId("routeValidation").textContent =
        result.route_validation ? "Available" : "Unavailable";

    byId("routeValidation").className =
        "result-value " + (result.route_validation ? "success" : "warning");

    byId("processingTime").textContent =
        hasNumericValue(result.request_processing_time_seconds)
            ? `${formatNumber(result.request_processing_time_seconds, 2)} s`
            : "Unavailable";

    function updateLeg(prefix, leg) {
        const staticVertices = leg.static_vertices;
        const dynamicVertices = leg.dynamic_vertices;

        byId(`${prefix}Static`).textContent =
            hasNumericValue(leg.static_distance_km)
                ? `${hasNumericValue(staticVertices) ? staticVertices : "—"} vertices / ` +
                  `${formatNumber(leg.static_distance_km, 3)} km`
                : "Route unavailable";

        byId(`${prefix}Dynamic`).textContent =
            hasNumericValue(leg.dynamic_distance_km)
                ? `${hasNumericValue(dynamicVertices) ? dynamicVertices : "—"} vertices / ` +
                  `${formatNumber(leg.dynamic_distance_km, 3)} km`
                : "Route unavailable";

        byId(`${prefix}Traffic`).textContent =
            leg.eta_type || "Configured road-condition costs; not live traffic";

        byId(`${prefix}Rerouted`).textContent =
            typeof leg.rerouted === "boolean"
                ? (leg.rerouted ? "Yes" : "No")
                : "Not compared";
    }

    updateLeg("leg1", leg1);
    updateLeg("leg2", leg2);

    byId("rawResult").textContent =
        JSON.stringify(result.raw_details || result, null, 2);

    renderMap(result);
}

async function api(path, payload) {
    const options = {
        method: payload === undefined ? "GET" : "POST",
        headers: {}
    };

    if (payload !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(payload);
    }

    const response = await fetch(path, options);
    let data;

    try {
        data = await response.json();
    } catch {
        throw new Error(
            `Server response was not valid JSON (HTTP ${response.status}).`
        );
    }

    if (!response.ok) {
        const error = new Error(
            data.message || `Request failed (HTTP ${response.status}).`
        );

        error.status = response.status;
        error.payload = data;
        throw error;
    }

    return data;
}

function setFormValues(payload) {
    byId("severity").value =
        payload.severity || "Critical";

    byId("trafficProfile").value =
        payload.traffic_profile || "normal";

    byId("condition").value =
        payload.condition || "Cardiac Emergency";

    byId("requiredFacility").value =
        payload.required_facility || "Emergency Department";

    byId("patientLocation").value =
        payload.patient_location || "Mode B Test Zone";

    byId("areaAddress").value =
        payload.area_address || "Mode B Test Emergency Location";
}

function loadValidatedSample() {
    setFormValues(SAMPLE_PAYLOAD);

    setRuntime(
        "Mode B sample scenario loaded. Browser GPS will supply the emergency coordinates."
    );
}

function loadDynamicTrafficTest() {
    setFormValues({
        ...SAMPLE_PAYLOAD,
        traffic_profile: "congested"
    });

    setRuntime(
        "Dynamic traffic test selected. Mode B uses its configured road-condition data."
    );
}

async function loadInitialStatus() {
    setFormValues(SAMPLE_PAYLOAD);

    try {
        const health = await api("/api/health");

        setRuntime(
            health.live_initialized
                ? "Mode B ready. Live services are initialized."
                : "Mode B ready. The server is online; the road graph will load when a request is submitted."
        );
    } catch (error) {
        setRuntime(
            `Mode B server unavailable: ${error.message}. Start the Mode B server and refresh.`
        );
    }
}

function sumLegs(routes, field) {
    const first = routes?.leg1?.[field];
    const second = routes?.leg2?.[field];

    if (!hasNumericValue(first) || !hasNumericValue(second)) {
        return null;
    }

    return Number(first) + Number(second);
}

function adaptModeBResult(
    emergency,
    recommendation,
    dispatch,
    payload,
    elapsedSeconds
) {
    const candidate =
        recommendation?.selected_candidate ||
        recommendation?.ranked_candidates?.[0] ||
        {};

    const dispatchRecord =
        dispatch && dispatch.status === "Dispatched" ? dispatch : {};

    const mapRoutes =
        recommendation?.map_routes || dispatch?.map_routes || null;

    const mapLocations =
        recommendation?.map_locations || dispatch?.map_locations || null;

    const routes = mapRoutes || {};
    const staticTotal = sumLegs(routes, "static_distance_km");
    const selectedTotal = sumLegs(routes, "dynamic_distance_km");

    const routeReady =
        recommendation?.map_route_status === "ready" &&
        !!mapRoutes &&
        !!mapLocations;

    const emergencyRecord = {
        ...(emergency || {}),
        emergency_id:
            emergency?.emergency_id ||
            recommendation?.emergency_id ||
            dispatch?.emergency_id ||
            "—",
        priority:
            emergency?.priority ||
            emergency?.priority_level ||
            emergency?.severity ||
            payload.severity,
        severity: payload.severity
    };

    const dispatchView = {
        ambulance_id:
            dispatchRecord.ambulance_id ||
            candidate.ambulance_id ||
            "—",

        ambulance_type:
            candidate.ambulance_type ||
            dispatchRecord.ambulance_type ||
            "—",

        hospital_id:
            dispatchRecord.hospital_id ||
            candidate.hospital_id ||
            "—",

        hospital_name:
            dispatchRecord.hospital_name ||
            candidate.hospital_name ||
            "Name unavailable",

        hospital_distance:
            candidate.hospital_distance_km ??
            candidate.transport_route_distance_km ??
            null,

        dynamic_status:
            dispatchRecord.status === "Dispatched"
                ? "Committed by Mode B"
                : (
                    dispatch?.status
                        ? `Not committed: ${dispatch.status}`
                        : "Recommended candidate; not committed"
                )
    };

    const detail = {
        status: "Mode B DSA recommendation",
        emergency: emergencyRecord,
        recommendation,
        dispatch,
        request_payload: payload,
        measured_browser_elapsed_seconds: elapsedSeconds,
        note:
            "Processing time is measured in the browser. Route times are estimates " +
            "based on configured Mode B graph and road conditions, not live traffic."
    };

    return {
        emergency: emergencyRecord,
        dispatch: dispatchView,
        locations: mapLocations,
        routes,
        total_static_distance_km: staticTotal,
        total_selected_distance_km: selectedTotal,
        traffic_profile: "Mode B - configured road-condition and modelled-speed costs",
        route_validation: routeReady,
        request_processing_time_seconds: elapsedSeconds,
        dispatch_status:
            dispatchRecord.status ||
            dispatch?.status ||
            "Recommendation calculated",
        raw_details: detail
    };
}

async function runDispatch() {
    if (!gpsReady) {
        updateGpsStatus(
            "A valid GPS location is required before dispatch.",
            "warning"
        );

        requestCurrentLocation();
        return;
    }

    const button = byId("runButton");
    button.disabled = true;
    button.textContent = "Running Mode B DSA...";

    const started = performance.now();

    let emergency = null;
    let recommendation = null;
    let dispatch = null;
    let payload = null;

    try {
        payload = {
            latitude: Number(byId("latitude").value),
            longitude: Number(byId("longitude").value),
            severity: byId("severity").value.trim(),
            condition: byId("condition").value.trim(),
            required_facility: byId("requiredFacility").value.trim(),
            patient_location: byId("patientLocation").value.trim(),
            area_address:
                byId("areaAddress").value.trim() ||
                "Live Emergency Location",
            patient_id: `MODEB-GPS-${Date.now()}`
        };

        if (
            !Number.isFinite(payload.latitude) ||
            payload.latitude < -90 ||
            payload.latitude > 90
        ) {
            throw new Error(
                "No valid latitude was obtained. Refresh GPS and try again."
            );
        }

        if (
            !Number.isFinite(payload.longitude) ||
            payload.longitude < -180 ||
            payload.longitude > 180
        ) {
            throw new Error(
                "No valid longitude was obtained. Refresh GPS and try again."
            );
        }

        for (const key of [
            "severity",
            "condition",
            "required_facility",
            "patient_location"
        ]) {
            if (!payload[key]) {
                throw new Error(
                    `Please complete ${key.replaceAll("_", " ")}.`
                );
            }
        }

        setRuntime(
            "Submitting emergency to Mode B and evaluating feasible ambulance–hospital pairs..."
        );

        const submitted = await api("/api/emergencies", payload);
        emergency = submitted.emergency;

        if (!emergency?.emergency_id) {
            throw new Error("Mode B did not return an emergency ID.");
        }

        const recommended = await api(
            `/api/recommend/${encodeURIComponent(emergency.emergency_id)}`,
            {}
        );

        recommendation = recommended.recommendation;

        if (
            recommended.status !== "success" ||
            recommendation?.status !== "Recommended"
        ) {
            throw new Error(
                recommended.message ||
                recommendation?.message ||
                recommendation?.status ||
                "Mode B found no feasible candidate."
            );
        }

        let elapsed = (performance.now() - started) / 1000;

        renderResult(
            adaptModeBResult(
                emergency,
                recommendation,
                null,
                payload,
                elapsed
            )
        );

        setRuntime(
            `Mode B recommendation ready for ${emergency.emergency_id}. ` +
            "Candidate selection and Static A*, Dynamic A*, and Time-aware A* route details are shown."
        );

        try {
            dispatch = await api(
                `/api/dispatch/${encodeURIComponent(emergency.emergency_id)}`,
                {}
            );

            elapsed = (performance.now() - started) / 1000;

            const display = adaptModeBResult(
                emergency,
                recommendation,
                dispatch.dispatch,
                payload,
                elapsed
            );

            display.raw_details = {
                ...display.raw_details,
                dispatch_api_response: dispatch
            };

            renderResult(display);

            if (
                dispatch.status === "success" &&
                dispatch.dispatch?.status === "Dispatched" &&
                dispatch.dispatch?.mode_b_selection_committed === true
            ) {
                setRuntime(
                    `Mode B dispatch committed in ${formatNumber(elapsed, 2)} seconds. ` +
                    `Ambulance ${dispatch.dispatch.ambulance_id} → ` +
                    `Hospital ${dispatch.dispatch.hospital_id}.`
                );
            } else {
                setRuntime(
                    "Mode B recommendation completed, but dispatch was not committed: " +
                    (dispatch.message ||
                     dispatch.dispatch?.status ||
                     "See raw result.")
                );
            }
        } catch (dispatchError) {
            elapsed = (performance.now() - started) / 1000;

            const display = adaptModeBResult(
                emergency,
                recommendation,
                dispatchError.payload?.dispatch || null,
                payload,
                elapsed
            );

            display.raw_details.dispatch_error = {
                message: dispatchError.message,
                status: dispatchError.status || null,
                response: dispatchError.payload || null
            };

            renderResult(display);

            setRuntime(
                "Mode B recommendation completed; dispatch was not committed: " +
                dispatchError.message
            );
        }
    } catch (error) {
        byId("rawResult").textContent = JSON.stringify({
            error: error.message || String(error),
            emergency,
            recommendation,
            dispatch,
            request_payload: payload
        }, null, 2);

        setRuntime(
            `Mode B request could not be completed: ${error.message || String(error)}`
        );
    } finally {
        button.disabled = false;
        button.textContent = "Run Mode B Dispatch";
    }
}

window.addEventListener("resize", () => {
    if (dispatchMap) dispatchMap.invalidateSize();
});

/*
 * Single startup sequence, matching Mode A:
 * initialize map, request GPS, load server status, then attach handlers.
 */
document.addEventListener("DOMContentLoaded", () => {
    initializeMap();
    requestCurrentLocation();
    loadInitialStatus();

    byId("refreshLocationButton").addEventListener(
        "click",
        requestCurrentLocation
    );

    byId("sampleButton").addEventListener(
        "click",
        loadValidatedSample
    );

    byId("congestedButton").addEventListener(
        "click",
        loadDynamicTrafficTest
    );

    byId("runButton").addEventListener(
        "click",
        runDispatch
    );
});