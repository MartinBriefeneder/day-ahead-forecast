FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /workspace
COPY pom.xml ./
COPY src ./src
RUN mvn -B -DskipTests package

FROM registry.access.redhat.com/ubi9/openjdk-21-runtime:1.24

LABEL name="forecast-backend" \
      org.opencontainers.image.title="forecast-backend" \
      org.opencontainers.image.description="Day-ahead forecast Quarkus backend" \
      io.k8s.display-name="forecast-backend" \
      io.k8s.description="Day-ahead forecast Quarkus backend"

ENV LANGUAGE='en_US:en'

COPY --from=build --chown=185 /workspace/target/quarkus-app/lib/ /deployments/lib/
COPY --from=build --chown=185 /workspace/target/quarkus-app/*.jar /deployments/
COPY --from=build --chown=185 /workspace/target/quarkus-app/app/ /deployments/app/
COPY --from=build --chown=185 /workspace/target/quarkus-app/quarkus/ /deployments/quarkus/

EXPOSE 8080
USER 185
ENV JAVA_OPTS_APPEND="-Dquarkus.http.host=0.0.0.0 -Djava.util.logging.manager=org.jboss.logmanager.LogManager"
ENV JAVA_APP_JAR="/deployments/quarkus-run.jar"

ENTRYPOINT [ "/opt/jboss/container/java/run/run-java.sh" ]
