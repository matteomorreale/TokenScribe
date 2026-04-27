"""
TokenScribe — Battery Service
Author: Matteo Morreale

Pre-built research prompt batteries covering different linguistic dimensions:
register, text length/structure, and morphological/lexical complexity.
Each battery is a Study with multiple Prompts ready for AI translation and experiment runs.
"""

BATTERY_STUDIES = [
    {
        "name": "Battery — Registro Linguistico",
        "description": (
            "Confronto del consumo di token tra registri linguistici: formale, accademico, "
            "narrativo, istruttivo e conversazionale. Progettata per isolare l'effetto del "
            "registro e del dominio sul tokenizer, a parità di lunghezza semantica."
        ),
        "prompts": [
            {
                "category": "formal_definition",
                "base_text": (
                    "Provide a precise scientific definition of entropy in thermodynamics, "
                    "including its unit of measurement and its relationship to the second law "
                    "of thermodynamics. Use formal academic language."
                ),
            },
            {
                "category": "academic_analytical",
                "base_text": (
                    "In two or three sentences, explain why inflation tends to rise when "
                    "unemployment falls, using economic reasoning. Refer to the Phillips curve."
                ),
            },
            {
                "category": "instructional_procedural",
                "base_text": (
                    "Write a short official notice informing employees that the office will be "
                    "closed on the next public holiday. Specify: the date, the reason, and the "
                    "arrangement for handling urgent matters during the closure."
                ),
            },
            {
                "category": "narrative_descriptive",
                "base_text": (
                    "Write a short paragraph describing a busy city market at midday. Focus on "
                    "sensory details: the sounds of vendors calling out, the smell of spices, "
                    "the colors of the produce, and the movement of the crowd."
                ),
            },
            {
                "category": "conversational_informal",
                "base_text": (
                    "Give three practical tips for sleeping better at night. Write in a friendly, "
                    "informal tone, as if advising a friend who has been struggling with insomnia."
                ),
            },
            {
                "category": "argumentative_comparative",
                "base_text": (
                    "In two or three sentences, compare renewable energy sources and fossil fuels "
                    "in terms of environmental impact and long-term economic cost. Take a position "
                    "and justify it briefly."
                ),
            },
        ],
    },
    {
        "name": "Battery — Lunghezza e Struttura Testuale",
        "description": (
            "Analisi della scalabilità del tokenizer al variare della lunghezza del testo "
            "(da una frase a un paragrafo esteso) e della complessità strutturale "
            "(testo continuo, lista numerata, struttura gerarchica). "
            "Permette di calcolare come il rapporto token/carattere evolve per writing system."
        ),
        "prompts": [
            {
                "category": "length_minimal",
                "base_text": "In one sentence, explain what artificial intelligence is.",
            },
            {
                "category": "length_short",
                "base_text": (
                    "Describe the water cycle in four to five sentences, suitable for a "
                    "middle school student. Cover evaporation, condensation, precipitation, "
                    "and collection."
                ),
            },
            {
                "category": "length_medium",
                "base_text": (
                    "Explain the main causes and consequences of the First World War in a "
                    "paragraph of approximately eight to ten sentences. Mention at least "
                    "three causes and two long-term consequences."
                ),
            },
            {
                "category": "structure_flat_list",
                "base_text": (
                    "List and briefly explain the five most important factors that determine "
                    "a country's economic growth. For each factor, provide one concrete "
                    "real-world example."
                ),
            },
            {
                "category": "structure_hierarchical",
                "base_text": (
                    "Outline the main phases of a software development project. For each phase, "
                    "list two or three key activities and state who is typically responsible "
                    "(project manager, developer, tester, etc.)."
                ),
            },
        ],
    },
    {
        "name": "Battery — Morfologia e Dominio Lessicale",
        "description": (
            "Prompts progettati per rivelare l'effetto della morfologia linguistica "
            "(agglutinazione, composizione di parole, declinazioni, genere grammaticale) "
            "e del lessico specializzato (tecnico-scientifico, medico, matematico) "
            "sul conteggio dei token. Particolarmente utile per confrontare lingue "
            "agglutinanti (turco, finlandese, coreano), logografiche (cinese, giapponese) "
            "e flessive ricche (russo, arabo, polacco)."
        ),
        "prompts": [
            {
                "category": "morphology_compound_technical",
                "base_text": (
                    "Explain the difference between machine learning, deep learning, and "
                    "neural networks. For each concept, give a one-sentence definition and "
                    "one practical application example."
                ),
            },
            {
                "category": "morphology_agglutinative_probe",
                "base_text": (
                    "Describe the daily responsibilities of a hospital administrator who "
                    "oversees multiple departments, coordinates interdisciplinary medical teams, "
                    "and manages the procurement of pharmaceutical and surgical supplies."
                ),
            },
            {
                "category": "morphology_rich_inflection",
                "base_text": (
                    "A student who had been studying all night finally fell asleep at dawn, "
                    "moments before her alarm went off. She had to take a decisive examination "
                    "that morning, one that would determine whether she could advance to the "
                    "next academic year. Recount her situation in the third person."
                ),
            },
            {
                "category": "morphology_grammatical_gender",
                "base_text": (
                    "Describe a female engineer who has just been promoted to lead a research "
                    "division. Then describe her male colleague who supported her candidacy "
                    "throughout the selection process. Use formal professional language."
                ),
            },
            {
                "category": "domain_scientific_abstract",
                "base_text": (
                    "Explain in plain language, without using formulas, why the square root of "
                    "a negative number is not a real number. Then explain what imaginary numbers "
                    "are and give one example of where they are used in physics or engineering."
                ),
            },
            {
                "category": "domain_medical_clinical",
                "base_text": (
                    "Describe the symptoms a patient might present with if suffering from "
                    "moderate dehydration after prolonged physical exertion. List the recommended "
                    "immediate treatment steps that a first responder should follow."
                ),
            },
        ],
    },
]


class BatteryService:

    @staticmethod
    def get_batteries() -> list:
        return BATTERY_STUDIES

    @staticmethod
    def get_status(study_model) -> list:
        """
        Returns BATTERY_STUDIES enriched with seeding status.
        Each entry gains: seeded (bool), study_id (int|None).
        """
        existing = {s["name"]: s for s in study_model.get_all()}
        result = []
        for battery in BATTERY_STUDIES:
            match = existing.get(battery["name"])
            result.append({
                **battery,
                "seeded": match is not None,
                "study_id": match["id"] if match else None,
                "prompt_count": len(battery["prompts"]),
            })
        return result

    @staticmethod
    def seed(study_model, prompt_model, battery_name: str | None = None) -> list:
        """
        Seeds one or all batteries.
        Skips batteries whose study name already exists (idempotent).
        Returns a list of result dicts: {name, created, study_id, prompts_added}.
        """
        existing_names = {s["name"] for s in study_model.get_all()}
        results = []
        for battery in BATTERY_STUDIES:
            if battery_name and battery["name"] != battery_name:
                continue
            if battery["name"] in existing_names:
                results.append({
                    "name": battery["name"],
                    "created": False,
                    "study_id": None,
                    "prompts_added": 0,
                })
                continue
            study_id = study_model.create(battery["name"], battery["description"])
            for p in battery["prompts"]:
                prompt_model.create(study_id, p["base_text"], p["category"])
            results.append({
                "name": battery["name"],
                "created": True,
                "study_id": study_id,
                "prompts_added": len(battery["prompts"]),
            })
        return results
