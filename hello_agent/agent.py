from google.adk.agents import Agent

root_agent = Agent(
    name="hello_agent",
    model="gemini-3.5-flash",
    description="Hello-world agent for the CSF Assessor Fleet. Proves ADK + Vertex AI wiring.",
    instruction=(
        "You are the hello-world agent for the CSF Assessor Fleet, a multi-agent system "
        "that performs NIST CSF 2.0 cybersecurity maturity assessments. "
        "When greeted, introduce yourself in one short sentence, name the 6 CSF Functions "
        "(Govern, Identify, Protect, Detect, Respond, Recover), and stop. Do not elaborate."
    ),
)
