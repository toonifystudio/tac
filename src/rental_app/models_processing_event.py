class ProcessingEvent(Base):
    __tablename__ = "processing_events"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    event_type = Column(String(128))
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    application = relationship("Application", backref="events")
