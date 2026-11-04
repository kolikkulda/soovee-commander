// iOS-style grouped lists (like Settings): titled sections of rows with an icon, a value and a chevron.
// Included inside SooveeViewController.

static UIFont *TextStyle(UIFontTextStyle style, UIFontWeight weight) {
    UIFontDescriptor *descriptor=[UIFontDescriptor preferredFontDescriptorWithTextStyle:style];
    UIFont *font=[UIFont systemFontOfSize:descriptor.pointSize weight:weight];
    return [[UIFontMetrics metricsForTextStyle:style] scaledFontForFont:font];
}

- (UILabel *)textLabel:(NSString *)text style:(UIFontTextStyle)style weight:(UIFontWeight)weight color:(UIColor *)color {
    UILabel *label=[UILabel new];label.text=text;label.numberOfLines=0;label.textColor=color;
    label.font=TextStyle(style,weight);label.adjustsFontForContentSizeCategory=YES;return label;
}

// A large screen title, optionally with a back button above it (top left, like a navigation bar).
- (void)screenTitle:(NSString *)title back:(NSString *)back action:(dispatch_block_t)action {
    if(back.length){
        UIButton *button=[UIButton buttonWithType:UIButtonTypeSystem];UIButtonConfiguration *cfg=[UIButtonConfiguration plainButtonConfiguration];
        cfg.title=back;cfg.image=[UIImage systemImageNamed:@"chevron.backward"];cfg.imagePadding=4;cfg.baseForegroundColor=Accent();cfg.contentInsets=NSDirectionalEdgeInsetsMake(10,0,10,12);
        cfg.preferredSymbolConfigurationForImage=[UIImageSymbolConfiguration configurationWithTextStyle:UIFontTextStyleBody scale:UIImageSymbolScaleMedium];
        button.configuration=cfg;button.contentHorizontalAlignment=UIControlContentHorizontalAlignmentLeading;
        [button addAction:[UIAction actionWithHandler:^(UIAction *value){action();}] forControlEvents:UIControlEventPrimaryActionTriggered];
        UIStackView *bar=[UIStackView new];bar.axis=UILayoutConstraintAxisHorizontal;[bar addArrangedSubview:button];[bar addArrangedSubview:[UIView new]];
        [self.content addArrangedSubview:bar];[self.content setCustomSpacing:0 afterView:bar];
    }
    UILabel *label=[self textLabel:title style:UIFontTextStyleLargeTitle weight:UIFontWeightBold color:UIColor.labelColor];
    label.accessibilityTraits=UIAccessibilityTraitHeader;[self.content addArrangedSubview:label];[self.content setCustomSpacing:18 afterView:label];
}

// One row. symbol in a small coloured tile, title and optional subtitle, optional value on the right,
// and a chevron when the row opens something. menu turns the whole row into a native pull-down menu.
- (UIView *)row:(NSString *)title detail:(NSString *)detail symbol:(NSString *)symbol tint:(UIColor *)tint value:(NSString *)value chevron:(BOOL)chevron menu:(UIMenu *)menu action:(dispatch_block_t)action {
    UIButton *row=[UIButton buttonWithType:UIButtonTypeCustom];row.translatesAutoresizingMaskIntoConstraints=NO;
    UIButtonConfiguration *base=[UIButtonConfiguration plainButtonConfiguration];base.contentInsets=NSDirectionalEdgeInsetsZero;base.background.backgroundColor=UIColor.clearColor;row.configuration=base;
    row.configurationUpdateHandler=^(UIButton *button){UIButtonConfiguration *cfg=button.configuration;cfg.background.backgroundColor=button.isHighlighted?[UIColor.labelColor colorWithAlphaComponent:.08]:UIColor.clearColor;button.configuration=cfg;};
    UIStackView *line=[UIStackView new];line.axis=UILayoutConstraintAxisHorizontal;line.alignment=UIStackViewAlignmentCenter;line.spacing=12;line.userInteractionEnabled=NO;line.translatesAutoresizingMaskIntoConstraints=NO;
    line.layoutMarginsRelativeArrangement=YES;line.directionalLayoutMargins=NSDirectionalEdgeInsetsMake(10,16,10,14);
    if(symbol.length){
        UIView *tile=[UIView new];tile.backgroundColor=tint?:Accent();tile.layer.cornerRadius=7;tile.layer.cornerCurve=kCACornerCurveContinuous;
        UIImageView *icon=[[UIImageView alloc]initWithImage:[UIImage systemImageNamed:symbol withConfiguration:[UIImageSymbolConfiguration configurationWithPointSize:15 weight:UIImageSymbolWeightSemibold]]];
        icon.tintColor=UIColor.whiteColor;icon.contentMode=UIViewContentModeCenter;icon.translatesAutoresizingMaskIntoConstraints=NO;[tile addSubview:icon];
        [NSLayoutConstraint activateConstraints:@[[tile.widthAnchor constraintEqualToConstant:30],[tile.heightAnchor constraintEqualToConstant:30],[icon.centerXAnchor constraintEqualToAnchor:tile.centerXAnchor],[icon.centerYAnchor constraintEqualToAnchor:tile.centerYAnchor]]];
        [line addArrangedSubview:tile];
    }
    UIStackView *texts=[UIStackView new];texts.axis=UILayoutConstraintAxisVertical;texts.spacing=2;
    UILabel *name=[self textLabel:title style:UIFontTextStyleBody weight:UIFontWeightRegular color:tint==UIColor.systemRedColor&&!symbol.length?UIColor.systemRedColor:UIColor.labelColor];[texts addArrangedSubview:name];
    if(detail.length)[texts addArrangedSubview:[self textLabel:detail style:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.secondaryLabelColor]];
    [line addArrangedSubview:texts];[texts setContentHuggingPriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
    if(value.length){BOOL actionValue=action&&!chevron&&!menu;   // e.g. "Pair": the value is the action itself
        UILabel *right=[self textLabel:value style:UIFontTextStyleBody weight:actionValue?UIFontWeightSemibold:UIFontWeightRegular color:actionValue?Accent():UIColor.secondaryLabelColor];right.numberOfLines=1;right.textAlignment=NSTextAlignmentRight;[right setContentCompressionResistancePriority:UILayoutPriorityDefaultHigh forAxis:UILayoutConstraintAxisHorizontal];[line addArrangedSubview:right];}
    if(chevron||menu){UIImageView *mark=[[UIImageView alloc]initWithImage:[UIImage systemImageNamed:menu?@"chevron.up.chevron.down":@"chevron.forward" withConfiguration:[UIImageSymbolConfiguration configurationWithPointSize:13 weight:UIImageSymbolWeightSemibold]]];mark.tintColor=UIColor.tertiaryLabelColor;[mark setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal];[line addArrangedSubview:mark];}
    [row addSubview:line];
    [NSLayoutConstraint activateConstraints:@[[line.leadingAnchor constraintEqualToAnchor:row.leadingAnchor],[line.trailingAnchor constraintEqualToAnchor:row.trailingAnchor],[line.topAnchor constraintEqualToAnchor:row.topAnchor],[line.bottomAnchor constraintEqualToAnchor:row.bottomAnchor],[row.heightAnchor constraintGreaterThanOrEqualToConstant:50]]];
    if(menu){row.menu=menu;row.showsMenuAsPrimaryAction=YES;}
    else if(action)[row addAction:[UIAction actionWithHandler:^(UIAction *v){action();}] forControlEvents:UIControlEventPrimaryActionTriggered];
    else row.userInteractionEnabled=NO;
    row.isAccessibilityElement=YES;row.accessibilityLabel=title;row.accessibilityValue=value.length?value:detail;
    row.accessibilityTraits=(action||menu)?UIAccessibilityTraitButton:UIAccessibilityTraitStaticText;
    return row;
}
- (UIView *)row:(NSString *)title detail:(NSString *)detail symbol:(NSString *)symbol tint:(UIColor *)tint action:(dispatch_block_t)action {
    return [self row:title detail:detail symbol:symbol tint:tint value:nil chevron:action!=nil menu:nil action:action];
}

// A section: small header, rows on a rounded card separated by hairlines, and an explanatory footer.
- (void)section:(NSString *)header rows:(NSArray<UIView *> *)rows footer:(NSString *)footer {
    UIStackView *block=[UIStackView new];block.axis=UILayoutConstraintAxisVertical;block.spacing=7;
    if(header.length){UILabel *label=[self textLabel:header.uppercaseString style:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];
        UIStackView *pad=[UIStackView new];pad.layoutMarginsRelativeArrangement=YES;pad.directionalLayoutMargins=NSDirectionalEdgeInsetsMake(0,16,0,16);[pad addArrangedSubview:label];label.accessibilityTraits=UIAccessibilityTraitHeader;[block addArrangedSubview:pad];}
    if(rows.count){
        UIStackView *card=[UIStackView new];card.axis=UILayoutConstraintAxisVertical;card.backgroundColor=Surface();card.layer.cornerRadius=12;card.layer.cornerCurve=kCACornerCurveContinuous;card.clipsToBounds=YES;
        for(NSUInteger i=0;i<rows.count;i++){
            if(i){UIView *rule=[UIView new];rule.backgroundColor=UIColor.separatorColor;UIView *holder=[UIView new];rule.translatesAutoresizingMaskIntoConstraints=NO;[holder addSubview:rule];
                [NSLayoutConstraint activateConstraints:@[[holder.heightAnchor constraintEqualToConstant:1/UIScreen.mainScreen.scale],[rule.leadingAnchor constraintEqualToAnchor:holder.leadingAnchor constant:58],[rule.trailingAnchor constraintEqualToAnchor:holder.trailingAnchor],[rule.topAnchor constraintEqualToAnchor:holder.topAnchor],[rule.bottomAnchor constraintEqualToAnchor:holder.bottomAnchor]]];
                [card addArrangedSubview:holder];}
            [card addArrangedSubview:rows[i]];
        }
        [block addArrangedSubview:card];
    }
    if(footer.length){UILabel *label=[self textLabel:footer style:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];
        UIStackView *pad=[UIStackView new];pad.layoutMarginsRelativeArrangement=YES;pad.directionalLayoutMargins=NSDirectionalEdgeInsetsMake(0,16,0,16);[pad addArrangedSubview:label];[block addArrangedSubview:pad];}
    [self.content addArrangedSubview:block];[self.content setCustomSpacing:28 afterView:block];
}

// The diagnostic log as a readable, scrollable, shareable sheet instead of an alert.
- (void)showLog {
    [self call:@"diagnostics" args:@[] then:^(NSString *text){
        UIViewController *sheet=[UIViewController new];sheet.view.backgroundColor=Background();sheet.title=T(@"Diagnostic log");
        // One readable line per event (time, level, message, and the last line of an error) instead of raw JSON.
        NSMutableArray *lines=[NSMutableArray new];
        for(NSString *raw in [text componentsSeparatedByString:@"\n"]){if(!raw.length)continue;
            NSDictionary *entry=[NSJSONSerialization JSONObjectWithData:[raw dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
            if(![entry isKindOfClass:NSDictionary.class]){[lines addObject:raw];continue;}
            NSString *time=[entry[@"time"] isKindOfClass:NSString.class]&&[entry[@"time"] length]>=19?[[entry[@"time"] substringWithRange:NSMakeRange(5,14)] stringByReplacingOccurrencesOfString:@"T" withString:@" "]:@"";
            NSString *level=[entry[@"level"] isKindOfClass:NSString.class]?entry[@"level"]:@"";
            NSMutableString *line=[NSMutableString stringWithFormat:@"%@  %@%@",time,[level isEqual:@"ERROR"]?@"⚠︎ ":@"",entry[@"event"]?:@""];
            NSString *trace=[entry[@"traceback"] isKindOfClass:NSString.class]?entry[@"traceback"]:@"";
            NSString *last=[[trace stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] componentsSeparatedByString:@"\n"].lastObject;
            if(last.length)[line appendFormat:@"\n      %@",last];
            [lines addObject:line];}
        UITextView *view=[UITextView new];view.editable=NO;view.text=lines.count?[lines componentsJoinedByString:@"\n"]:T(@"The log is empty.");view.backgroundColor=Background();view.textColor=UIColor.labelColor;
        view.font=[[UIFontMetrics metricsForTextStyle:UIFontTextStyleFootnote] scaledFontForFont:[UIFont monospacedSystemFontOfSize:12 weight:UIFontWeightRegular]];view.adjustsFontForContentSizeCategory=YES;
        view.textContainerInset=UIEdgeInsetsMake(12,12,24,12);sheet.view=view;
        UINavigationController *navigation=[[UINavigationController alloc]initWithRootViewController:sheet];navigation.overrideUserInterfaceStyle=self.overrideUserInterfaceStyle;navigation.view.tintColor=UIColor.systemBlueColor;
        __weak UINavigationController *weakNavigation=navigation;
        sheet.navigationItem.leftBarButtonItem=[[UIBarButtonItem alloc]initWithPrimaryAction:[UIAction actionWithTitle:T(@"Done") image:nil identifier:nil handler:^(UIAction *a){[weakNavigation dismissViewControllerAnimated:YES completion:nil];}]];
        UIBarButtonItem *share=[[UIBarButtonItem alloc]initWithBarButtonSystemItem:UIBarButtonSystemItemAction primaryAction:[UIAction actionWithHandler:^(UIAction *a){
            UIActivityViewController *activity=[[UIActivityViewController alloc]initWithActivityItems:@[view.text?:@""] applicationActivities:nil];
            activity.popoverPresentationController.barButtonItem=weakNavigation.topViewController.navigationItem.rightBarButtonItem;[weakNavigation presentViewController:activity animated:YES completion:nil];}] menu:nil];
        share.accessibilityLabel=T(@"Share log");sheet.navigationItem.rightBarButtonItem=share;
        [self presentViewController:navigation animated:YES completion:^{[view scrollRangeToVisible:NSMakeRange(view.text.length,0)];}];
    }];
}
