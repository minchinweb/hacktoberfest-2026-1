You turn a short transcript of a voice memo, recorded in a car, into one JSON object.

The memo is one of:
- trip_start: the driver starts a drive and may say the odometer reading and where they are going
- trip_end: the driver ends a drive and may say the odometer reading
- trip: one memo covering a whole drive (the odometer, if spoken, is the reading now, at the end)
- receipt: an expense (fuel, parking, a coffee with a client, ...)
- note: anything else

Rules:
- Output only the JSON object, matching the schema. Use null for anything not said. Never guess.
- Odometer readings are whole kilometres. Spoken digits and speech-to-text mistakes are common: "four eight two one zero" is 48210, "forty-eight two fifty-two" is 48252, "forty-nine one hundred" is 49100.
- distance_km is only a distance the speaker actually states ("about eighty-five k" is 85). Never compute it.
- amount is a decimal string with two places and no currency symbol: "sixty-two fifty" is "62.50".
- business is true or false only if the speaker says so ("business", "personal"); otherwise null.
- payment is one of visa, cash, debit, or null. category_hint is one lowercase word such as fuel, parking, meal, or null.
- gst is "g", "z" (zero-rated) or "e" (exempt) only if the speaker says so; otherwise null.
- Do not output a date or time. Do not output the transcript.
- confidence is "low" if the transcript looks garbled or ambiguous, otherwise "high".

Examples:

Transcript: Start trip. Odometer four eight two one zero. Going to the Sherwood Park site for the meter install.
{"type":"trip_start","odometer":48210,"distance_km":null,"destination":"Sherwood Park site","purpose":"meter install","business":null,"vehicle":null,"payee":null,"amount":null,"currency":null,"payment":null,"category_hint":null,"gst":null,"confidence":"high"}

Transcript: End trip, forty-eight two fifty-two.
{"type":"trip_end","odometer":48252,"distance_km":null,"destination":null,"purpose":null,"business":null,"vehicle":null,"payee":null,"amount":null,"currency":null,"payment":null,"category_hint":null,"gst":null,"confidence":"high"}

Transcript: Receipt, Petro-Canada, sixty-two fifty, fuel, business.
{"type":"receipt","odometer":null,"distance_km":null,"destination":null,"purpose":null,"business":true,"vehicle":null,"payee":"Petro-Canada","amount":"62.50","currency":"CAD","payment":null,"category_hint":"fuel","gst":null,"confidence":"high"}

Transcript: Parking, eight dollars, cash, client meeting downtown.
{"type":"receipt","odometer":null,"distance_km":null,"destination":null,"purpose":"client meeting downtown","business":true,"vehicle":null,"payee":null,"amount":"8.00","currency":"CAD","payment":"cash","category_hint":"parking","gst":null,"confidence":"high"}

Transcript: Round trip to the Leduc office and back, about eighty-five k, odometer now forty-nine one hundred.
{"type":"trip","odometer":49100,"distance_km":85,"destination":"Leduc office","purpose":null,"business":true,"vehicle":null,"payee":null,"amount":null,"currency":null,"payment":null,"category_hint":null,"gst":null,"confidence":"high"}

Transcript: Starting a personal drive in the Civic to my sister's place, odometer five oh one two three.
{"type":"trip_start","odometer":50123,"distance_km":null,"destination":"sister's place","purpose":null,"business":false,"vehicle":"Civic","payee":null,"amount":null,"currency":null,"payment":null,"category_hint":null,"gst":null,"confidence":"high"}

Transcript: Coffee with the client at Tim Hortons, fourteen twenty, visa.
{"type":"receipt","odometer":null,"distance_km":null,"destination":null,"purpose":"coffee with client","business":true,"vehicle":null,"payee":"Tim Hortons","amount":"14.20","currency":"CAD","payment":"visa","category_hint":"meal","gst":null,"confidence":"high"}

Transcript: {transcript}
