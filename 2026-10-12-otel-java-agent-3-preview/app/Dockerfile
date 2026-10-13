# API de pedidos (só JDK + JDBC) instrumentada pelo OpenTelemetry Java agent.
# Nenhuma dependência de OpenTelemetry no código: o agent é anexado no runtime.
FROM eclipse-temurin:21.0.12_8-jdk

ARG OTEL_JAVAAGENT_VERSION=2.32.0
ARG PGJDBC_VERSION=42.7.14

WORKDIR /app

# Java agent 2.32.0 = release candidate do 3.0 (blog do OpenTelemetry, 06/10/2026)
ADD https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v${OTEL_JAVAAGENT_VERSION}/opentelemetry-javaagent.jar /otel/opentelemetry-javaagent.jar
ADD https://github.com/pgjdbc/pgjdbc/releases/download/REL${PGJDBC_VERSION}/postgresql-${PGJDBC_VERSION}.jar /app/lib/postgresql.jar

COPY App.java .
RUN javac -cp lib/postgresql.jar -d classes App.java

EXPOSE 8080
ENTRYPOINT ["java", "-javaagent:/otel/opentelemetry-javaagent.jar", "-cp", "classes:lib/postgresql.jar", "App"]
