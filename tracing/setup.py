import os
from opentelemetry import trace
from opentelemetry.exporter.jaeger import JaegerExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Set up Jaeger tracing
resource = Resource.create({"service.name": os.getenv("SERVICE_NAME", "default_service")})

trace.set_tracer_provider(TracerProvider(resource=resource))

ejager_exporter = JaegerExporter(
    agent_host_name=os.getenv("JAEGER_HOST", "localhost"),
    agent_port=int(os.getenv("JAEGER_PORT", 6831)),
)

trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(jager_exporter))

# Usage:
# tracer = trace.get_tracer(__name__)
# with tracer.start_span("my_span"):
#     # do some work
