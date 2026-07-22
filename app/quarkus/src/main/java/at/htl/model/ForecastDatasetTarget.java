package at.htl.model;

public enum ForecastDatasetTarget {
    CONSUMPTION("consumption", DirectionType.CONSUMPTION),
    GENERATION("generation", DirectionType.DELIVERY);

    private final String columnName;
    private final DirectionType direction;

    ForecastDatasetTarget(String columnName, DirectionType direction) {
        this.columnName = columnName;
        this.direction = direction;
    }

    public String columnName() {
        return columnName;
    }

    public DirectionType direction() {
        return direction;
    }

    public static ForecastDatasetTarget parse(String value) {
        for (ForecastDatasetTarget target : values()) {
            if (target.columnName.equals(value)) {
                return target;
            }
        }
        throw new IllegalArgumentException("Unsupported target: " + value + ". Supported targets are consumption and generation.");
    }
}
