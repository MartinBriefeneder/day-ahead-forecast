FROM eclipse-temurin:21-jre-alpine

WORKDIR /app
COPY target/quarkus-app/ ./
COPY ./data/csv_Archiv/ data/csv_Archiv/
EXPOSE 8080

CMD ["java", "-Dquarkus.profile=dev", "-Denergy.import.command.directory=/app/data/csv_Archiv", "-jar", "quarkus-run.jar"]
