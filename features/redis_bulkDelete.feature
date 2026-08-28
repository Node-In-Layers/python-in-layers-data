@redis
Feature: Redis Bulk Delete

  Scenario: Bulk delete
    Given an orm is setup
    Given ModelList1 is created and inserted into the database
    When bulk delete is executed on model named ModelA with ids "edf73dba-216a-4e10-a38f-398a4b38350a, 2c3e6547-2d6b-44c3-ad2c-1220a3d305be, ed1dc8ff-fdc5-401c-a229-8566a418ceb5"
    And search named EmptySearch is executed on model named ModelA
    Then 7 instances are found
