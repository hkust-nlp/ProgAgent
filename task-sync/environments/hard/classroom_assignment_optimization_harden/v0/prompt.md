You are responsible for producing a complete, conflict-free weekly room-allocation schedule for a school. Every class section offered this term must be assigned to a specific room during each of its required weekly meeting periods, no room may host more than one class in the same time slot, and no teacher may be double-booked into two classes in the same day-and-period combination.

The policy and configuration documents stored alongside the data are the authoritative specification for the schedule. They define the structure of the school week, how each class's required number of weekly meetings is derived, teacher availability and load limits, which rooms a class may occupy, and how to prioritize when several rooms or classes compete for the same placement. Follow them exactly.

As you finalize the timetable, record every period assignment in the school's room-booking system so that the central database reflects the complete schedule.

Construct the weekly timetable and save it as `weekly_schedule.csv`. The file must contain exactly these columns in this order: `day`, `period`, `class_id`, `class_name`, `room_id`, `room_name`, `teacher_id`, `teacher_name`. Sort the rows first by day of the week in calendar order starting from Monday, then by period number in ascending order, then by class identifier in ascending order.

After writing the schedule file, include in your final response a single summary line in exactly this format, substituting the correct totals from the schedule you produced: "Scheduling Summary: X classes across Y periods using Z rooms" where X is the count of distinct classes scheduled, Y is the total number of individual period assignments in the file, and Z is the count of distinct rooms that appear at least once in the schedule.
